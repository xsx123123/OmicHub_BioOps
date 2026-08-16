import os
import base64
import mimetypes
import tiktoken
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from loguru import logger
from jinja2 import Template, Environment, FileSystemLoader
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import ValidationError
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.chat import ChatCompletion
from openai import OpenAI


from .schemas import RNASeqResult

class AIInterpretationError(Exception):
    """AI 模块通用异常基类"""
    pass

@dataclass
class AIResponse:
    content: str
    usage: Dict[str, int]
    model: str
    provider: str

class AIInterpreter:
    def __init__(self, 
                 model: str = "doubao-seed-1-6-251015", 
                 provider: str = "volcengine",
                 base_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 template_dir: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        初始化 AI 解读器。

        Args:
            model: 模型 ID
            provider: 服务提供商 ("volcengine" or "aliyun")
            base_url: 自定义 API Base URL (用于 Aliyun/OpenAI 兼容)
            api_key: API Key (默认读取环境变量 ARK_API_KEY 或 DASHSCOPE_API_KEY)
            template_dir: Jinja2 模板目录
            config: 完整的 ai_config 字典，用于 Fallback 逻辑
        """
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.api_key_override = api_key
        self.config = config or {}
        
        self.client = self._init_client(provider, base_url, api_key)

        # 初始化模板环境
        if template_dir:
            self.env = Environment(loader=FileSystemLoader(template_dir))
        else:
            self.env = None 

    def _init_client(self, provider: str, base_url: str = None, api_key: str = None) -> Any:
        """初始化特定 Provider 的客户端"""
        client = None
        if provider == "volcengine":
            key = api_key or os.environ.get("ARK_API_KEY")
            if not key:
                logger.warning(f"未检测到 ARK_API_KEY (Provider: {provider})")
            else:
                client = Ark(api_key=key, timeout=120)
                
        elif provider == "aliyun":
            key = api_key or os.environ.get("DASHSCOPE_API_KEY")
            if not key:
                logger.warning(f"未检测到 DASHSCOPE_API_KEY (Provider: {provider})")
            else:
                # Aliyun uses standard OpenAI client with custom base_url
                # Try to get base_url from config if not provided
                if not base_url and self.config:
                     base_url = self.config.get("aliyun", {}).get("base_url")
                
                client = OpenAI(
                    api_key=key,
                    base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    timeout=120
                )
        else:
            logger.error(f"不支持的 Provider: {provider}")
            
        return client 

    def validate_data(self, data: Dict[str, Any]) -> RNASeqResult:
        """验证输入数据是否符合 Schema"""
        try:
            return RNASeqResult(**data)
        except ValidationError as e:
            logger.error(f"输入数据校验失败: {e}")
            raise AIInterpretationError(f"数据格式错误: {e}")

    def _estimate_tokens(self, text: str) -> int:
        """预估文本 Token 数量 (使用 cl100k_base 编码)"""
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            # 降级方案：粗略估计 (中文/英文混合环境，约 1 token ≈ 2-3 chars)
            return len(text) // 3

    def _truncate_data(self, data: RNASeqResult, max_tokens: int = 30000, template_path: str = "") -> RNASeqResult:
        """
        如果 Token 超出限制，递归截断数据 (Top-N).
        """
        # 初始检查
        prompt = self.render_prompt(template_path, data)
        token_count = self._estimate_tokens(prompt)
        
        if token_count <= max_tokens:
            return data
            
        logger.warning(f"Token 预估 ({token_count}) 超过限制 ({max_tokens})，执行数据截断...")
        
        # 策略 1: 截断 Top Genes (保留前 50 -> 20 -> 10)
        limits = [50, 20, 10]
        original_genes = data.top_genes
        
        for limit in limits:
            if len(original_genes) <= limit:
                continue
                
            logger.info(f"截断 Top Genes 至前 {limit} 个...")
            data.top_genes = original_genes[:limit]
            
            prompt = self.render_prompt(template_path, data)
            if self._estimate_tokens(prompt) <= max_tokens:
                return data
        
        # 策略 2: 截断 Pathways (保留前 10 -> 5)
        limits_path = [10, 5]
        original_paths = data.enrichment.top_pathways
        
        for limit in limits_path:
            if len(original_paths) <= limit:
                continue
                
            logger.info(f"截断 Pathways 至前 {limit} 个...")
            data.enrichment.top_pathways = original_paths[:limit]
            
            prompt = self.render_prompt(template_path, data)
            if self._estimate_tokens(prompt) <= max_tokens:
                return data
                
        logger.warning("数据截断后仍超出 Token 限制，可能会导致 API 错误。")
        return data

    def _verify_and_extract_content(self, raw_response: str) -> str:
        """
        验证 XML 标签完整性并提取 Markdown 内容。
        """
        start_tag = "<bio_report>"
        end_tag = "</bio_report>"
        
        if start_tag not in raw_response or end_tag not in raw_response:
            logger.warning("LLM 返回未包含完整的 <bio_report> 标签。尝试自动修复或提取...")
            
            content = raw_response
            if start_tag in content:
                content = content.split(start_tag)[1]
            if end_tag in content:
                content = content.split(end_tag)[0]
            return content.strip()
            
        return raw_response.split(start_tag)[1].split(end_tag)[0].strip()

    def _encode_file(self, file_path: str) -> Optional[str]:
        """将文件编码为 Base64 Data URI"""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"文件不存在，跳过: {file_path}")
            return None
        
        mime_type, _ = mimetypes.guess_type(path)
        if not mime_type:
            mime_type = 'application/octet-stream'
            
        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
                return f"data:{mime_type};base64,{encoded}"
        except Exception as e:
            logger.error(f"读取文件失败 {file_path}: {e}")
            return None

    def render_prompt(self, template_path: str, data: RNASeqResult) -> str:
        """渲染 Prompt 模板"""
        if not Path(template_path).exists():
             raise AIInterpretationError(f"模板文件不存在: {template_path}")
        
        # 临时创建一个 loader 指向模板所在目录
        env = Environment(loader=FileSystemLoader(os.path.dirname(template_path)))
        template = env.get_template(os.path.basename(template_path))
        
        # 将 Pydantic 对象转为 dict 传给模板
        return template.render(data=data.model_dump(), project_id=data.project_info.id)

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _call_provider_internal(self, 
                 system_prompt: str, 
                 user_content: List[Dict], 
                 thinking: bool = True,
                 temperature: float = 0.6,
                 top_p: float = 0.9,
                 trace_id: str = "") -> AIResponse:
        """
        [内部方法] 单次调用 LLM API，包含自动重试机制。
        """
        if not self.client:
            raise AIInterpretationError("API Client 未初始化")

        extra_params = {
            "temperature": temperature,
            "top_p": top_p
        }
        
        # Thinking param is specific to VolcEngine/DeepSeek on Ark
        if thinking and self.provider == "volcengine":
            extra_params["thinking"] = {"type": "enabled"}
        # For Aliyun/OpenAI, we ignore 'thinking' param or handle differently if needed

        logger.info(f"[{trace_id}] 调用模型 {self.model} ({self.provider}) | Params: temp={temperature}, top_p={top_p}")
        logger.debug(f"System Prompt: {system_prompt}")
        
        try:
            # Both Ark and OpenAI clients share the same interface for chat.completions.create
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                **extra_params
            )
            
            # Log usage if available
            usage = {}
            if hasattr(response, 'usage'):
                logger.debug(f"Token Usage: {response.usage}")
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }

            return AIResponse(
                content=response.choices[0].message.content,
                usage=usage,
                model=self.model,
                provider=self.provider
            )
        except Exception as e:
            logger.warning(f"[{trace_id}] API 调用失败 ({self.provider}): {str(e)}")
            raise

    def execute_inference(self, 
                          system_prompt: str, 
                          user_content: List[Dict], 
                          trace_id: str,
                          thinking: bool = True,
                          temperature: float = 0.6,
                          top_p: float = 0.9) -> AIResponse:
        """
        执行推理，包含自动降级 (Fallback) 逻辑。
        """
        # 1. 尝试主 Provider
        try:
            return self._call_provider_internal(system_prompt, user_content, thinking, temperature, top_p, trace_id)
        except Exception as e:
            logger.error(f"[{trace_id}] 主 Provider ({self.provider}) 失败: {e}")
            
            # 2. 检查降级配置
            fallback_providers = self.config.get("fallback_providers", [])
            if not fallback_providers:
                raise e # 无降级策略，直接抛出异常
            
            logger.warning(f"[{trace_id}] 触发自动降级策略，尝试 Providers: {fallback_providers}")
            
            # 保存原始状态以便恢复 (可选，这里我们直接修改 self 状态)
            original_provider = self.provider
            original_model = self.model
            original_client = self.client
            
            for fb_provider in fallback_providers:
                if fb_provider == original_provider:
                    continue # 跳过自己
                    
                logger.info(f"正在切换到备用 Provider: {fb_provider}")
                
                # 获取备用 Provider 的默认模型
                fb_models = self.config.get(fb_provider, {}).get("model", [])
                fb_model = fb_models[0] if isinstance(fb_models, list) and fb_models else (fb_models if isinstance(fb_models, str) else None)
                
                if not fb_model:
                    logger.warning(f"Provider {fb_provider} 未配置模型，跳过")
                    continue
                
                # 重新初始化 Client
                try:
                    self.provider = fb_provider
                    self.model = fb_model
                    self.client = self._init_client(fb_provider)
                    
                    if not self.client:
                        logger.warning(f"Provider {fb_provider} 客户端初始化失败，跳过")
                        continue
                        
                    # 尝试调用
                    return self._call_provider_internal(system_prompt, user_content, thinking, temperature, top_p, trace_id)
                    
                except Exception as fb_e:
                    logger.error(f"[{trace_id}] 备用 Provider {fb_provider} 调用失败: {fb_e}")
                    # 继续尝试下一个
            
            # 所有降级都失败，恢复原始状态并抛出异常
            self.provider = original_provider
            self.model = original_model
            self.client = original_client
            raise AIInterpretationError("所有 Provider (含降级) 均调用失败") from e

    def _calculate_cost(self, response: AIResponse) -> float:
        """
        计算 API 调用成本 (CNY).
        基于 config.yaml 中的 pricing 配置。
        """
        pricing_config = self.config.get("pricing", {})
        model_pricing = pricing_config.get(response.model)
        
        # 如果未找到特定模型定价，尝试使用 default
        if not model_pricing:
            model_pricing = pricing_config.get("default", {"input": 0.0, "output": 0.0})
            
        input_price = model_pricing.get("input", 0.0)
        output_price = model_pricing.get("output", 0.0)
        
        prompt_tokens = response.usage.get("prompt_tokens", 0)
        completion_tokens = response.usage.get("completion_tokens", 0)
        
        cost = (prompt_tokens / 1000 * input_price) + (completion_tokens / 1000 * output_price)
        return round(cost, 6)

    def generate_report(self, 
                        data_json: Dict[str, Any], 
                        template_path: str, 
                        attachments: List[str] = [],
                        output_path: Optional[str] = None,
                        temperature: float = 0.6,
                        top_p: float = 0.9,
                        trace_id: str = None) -> str:
        """
        主入口：生成完整报告。
        """
        if not trace_id:
            trace_id = str(uuid.uuid4())[:8]

        logger.debug(f"[{trace_id}] 开始执行 generate_report...")
        
        # 1. 验证数据
        validated_data = self.validate_data(data_json)
        
        # 2. Token 截断 (保护机制)
        # 获取配置中的 max_tokens，默认 30k (Doubao 32k window)
        max_tokens = self.config.get("max_input_tokens", 30000)
        validated_data = self._truncate_data(validated_data, max_tokens, template_path)
        
        # 3. 准备 Prompt
        text_prompt = self.render_prompt(template_path, validated_data)
        
        # 4. 准备多模态内容
        user_content = []
        # 先加图片/文件
        for path in attachments:
            data_uri = self._encode_file(path)
            if data_uri:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": data_uri}
                })
        # 再加文本
        user_content.append({"type": "text", "text": text_prompt})
        
        # 5. 执行调用
        try:
            target_lang = validated_data.project_info.language
            from .prompt_assets import load_report_prompt
            sys_prompt = load_report_prompt("system.md").replace(
                "{{target_language}}", str(target_lang)
            )
            
            ai_response = self.execute_inference(
                system_prompt=sys_prompt,
                user_content=user_content,
                trace_id=trace_id,
                temperature=temperature,
                top_p=top_p
            )
            
            # 计算并记录成本
            cost = self._calculate_cost(ai_response)
            logger.info(f"[{trace_id}] 生成成功 | Cost: ¥{cost} | Tokens: {ai_response.usage}")
            
            # 6. 验证和提取内容
            final_result = self._verify_and_extract_content(ai_response.content)
            
        except Exception as e:
            logger.error(f"[{trace_id}] 最终生成失败: {e}")
            return f"生成失败，请检查日志 (TraceID: {trace_id})。错误信息: {e}"

        # 7. 输出
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(final_result)
            logger.info(f"[{trace_id}] 报告已保存至: {output_path}")
            
        return final_result
