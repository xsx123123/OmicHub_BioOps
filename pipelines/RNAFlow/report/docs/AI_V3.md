# **BioReport V3: Knowledge-Augmented Autonomous Agent Framework**

# **(基于知识增强的自主智能体转录组解读系统)**

## **1\. 核心理念 (Core Philosophy)**

BioReport V3 标志着从“自动化报告生成”向“自主科学发现”的范式转变。系统不再依赖静态模板，而是构建了一个具备**感知 (Perception)**、**记忆 (Memory)** 和 **推理 (Reasoning)** 能力的智能体。

* **V1 (Script):** 数据 \-\> 模板 \-\> 文本  
* **V2 (RAG):** 数据 \+ 搜索 \-\> 文本  
* **V3 (Agent):** 数据 \-\> **主动规划** \-\> **知识库检索** \-\> **逻辑反思** \-\> **科学发现**

该架构专门设计用于解决 LLM 在生物医学领域的**幻觉 (Hallucination)** 问题，并具备发现“隐蔽关联”的能力，符合 *Nature Communications* 或 *Briefings in Bioinformatics* 等期刊对“AI for Science”方法学的要求。

## **2\. 系统架构 (System Architecture)**

graph TD  
    %% Define Styles  
    classDef memory fill:\#f9f,stroke:\#333,stroke-width:2px;  
    classDef agent fill:\#bbf,stroke:\#333,stroke-width:2px;  
    classDef data fill:\#dfd,stroke:\#333,stroke-width:2px;

    subgraph "External World (Input)"  
        RNA\[RNA-seq Analysis Results\\n(JSON/YAML)\]:::data  
        User\[User Query / Hypothesis\]:::data  
    end

    subgraph "Hippocampus (Long-term Memory)"  
        KB\_Raw\[Knowledge Sources\\nPubMed/TCGA/OncoKB\]  
        Embed\[Bio-Embedding Model\\n(BioBERT/Doubao-Emb)\]  
        VDB\[(Bio-VectorDB\\nChroma/Milvus)\]:::memory  
          
        KB\_Raw \--\> Embed \--\> VDB  
    end

    subgraph "Prefrontal Cortex (Reasoning Agent)"  
        Agent\[ReAct Agent Core\]:::agent  
        Planner\[Chain-of-Thought Planner\]  
        Critic\[Hallucination Critic\]  
          
        Agent \<--\> Planner  
        Agent \<--\> Critic  
    end

    subgraph "Tools (Effectors)"  
        T1\[Tool: Gene Lookup\]  
        T2\[Tool: Stat Validator\]  
        T3\[Tool: Literature Search\]  
    end

    %% Data Flow  
    RNA \--\> Agent  
    User \--\> Agent  
    Agent \--\>|Query| T1  
    T1 \--\>|Retrieve| VDB  
    VDB \--\>|Context| T1  
    T1 \--\>|Result| Agent  
    Agent \--\>|Draft| Critic  
    Critic \-- Approved \--\> Report\[Final Insight Report\]  
    Critic \-- Rejected \--\> Agent

## **3\. 项目目录结构 (Directory Structure)**

bioreport/  
├── ai/  
│   ├── rag/                \# \[核心组件\] 检索增强生成模块  
│   │   ├── vector\_store.py \# 向量数据库接口 (ChromaDB/Milvus)  
│   │   ├── embeddings.py   \# 领域适配 Embedding 模型封装  
│   │   └── loader.py       \# 知识清洗与切片 (ETL)  
│   ├── agent/              \# \[大脑\] 智能体核心  
│   │   ├── core.py         \# Agent 编排 (LangChain/LangGraph)  
│   │   ├── tools.py        \# 工具定义 (Tools Definition)  
│   │   └── prompts.py      \# 学术级 System Prompts  
│   ├── schemas.py          \# Pydantic 数据契约  
│   └── \_\_init\_\_.py  
├── data/  
│   └── knowledge\_base/     \# 存放原始知识文件 (CSV, PDF, MD)  
├── scripts/  
│   └── build\_knowledge\_base.py \# \[Fuel\] 知识库构建脚本  
└── main.py                 \# 入口程序

## **4\. 核心代码实现 (Core Implementation)**

### **4.1. 海马体：向量数据库 (ai/rag/vector\_store.py)**

负责长时记忆的存储与检索。为了发文章，这里预留了切换不同 Embedding 模型的接口。

import chromadb  
from chromadb.utils import embedding\_functions  
import os

class BioKnowledgeBase:  
    """  
    生物医学知识库管理类 (Bio-VectorDB Manager)  
    """  
    def \_\_init\_\_(self, persist\_path="./bio\_vector\_db\_storage"):  
        \# 初始化持久化存储  
        self.client \= chromadb.PersistentClient(path=persist\_path)  
          
        \# 使用轻量级 Sentence Transformer 或 豆包 Embedding API  
        \# 论文卖点：可以使用是在 BioMedical 语料上微调过的模型  
        self.emb\_fn \= embedding\_functions.SentenceTransformerEmbeddingFunction(  
            model\_name="all-MiniLM-L6-v2"   
        )  
          
        \# 获取或创建集合  
        self.collection \= self.client.get\_or\_create\_collection(  
            name="cancer\_insights\_v1",  
            embedding\_function=self.emb\_fn,  
            metadata={"description": "Knowledge base for HCC drug resistance"}  
        )

    def add\_knowledge(self, documents: list\[str\], metadatas: list\[dict\], ids: list\[str\]):  
        """  
        向海马体注入知识  
        """  
        if not documents:  
            return  
        self.collection.upsert(  
            documents=documents,  
            metadatas=metadatas,  
            ids=ids  
        )  
        print(f"\[BioDB\] Successfully indexed {len(documents)} knowledge fragments.")

    def query\_context(self, query\_text: str, n\_results=3) \-\> str:  
        """  
        语义检索：根据 Agent 的问题查找相关背景  
        """  
        results \= self.collection.query(  
            query\_texts=\[query\_text\],  
            n\_results=n\_results  
        )  
          
        if not results\['documents'\]\[0\]:  
            return "No specific biological context found in the database."  
              
        \# 拼接检索到的上下文  
        context\_str \= "\\n---\\n".join(results\['documents'\]\[0\])  
        return context\_str

### **4.2. 手与眼：Agent 工具集 (ai/agent/tools.py)**

将数据库检索能力封装为 LLM 可理解的工具。

from langchain.tools import tool  
from bioreport.ai.rag.vector\_store import BioKnowledgeBase

\# 初始化知识库实例  
kb \= BioKnowledgeBase()

@tool  
def lookup\_gene\_function(gene\_symbol: str):  
    """  
    \[RAG Tool\] Queries the internal biological vector database for specific gene functions,  
    pathways, drug sensitivities, and prognostic values in Cancer.  
      
    Use this tool whenever you encounter a differentially expressed gene (DEG)   
    and need to understand its biological significance.  
      
    Args:  
        gene\_symbol: The official gene symbol (e.g., 'TP53', 'IL6').  
    """  
    print(f"🕵️ Agent is researching gene: {gene\_symbol}...")  
    \# 构造更丰富的查询语句以提高检索命中率  
    query \= f"Molecular function, signaling pathway, and clinical significance of {gene\_symbol} in Hepatocellular Carcinoma (HCC) and Sorafenib resistance."  
    context \= kb.query\_context(query)  
    return context

@tool  
def statistical\_validator(p\_value: float, log2fc: float):  
    """  
    \[Logic Tool\] Validates if a gene meets the strict significance threshold for this study.  
    Threshold: p\_adj \< 0.05 AND |log2FC| \> 1.0.  
    """  
    is\_sig \= float(p\_value) \< 0.05 and abs(float(log2fc)) \> 1.0  
    return "Significant" if is\_sig else "Not Significant (Filter Out)"

### **4.3. 大脑：ReAct Agent 核心 (ai/agent/core.py)**

这是整个 V3 系统的中枢，负责编排思考过程。

from langchain.agents import AgentExecutor, create\_react\_agent  
from langchain.prompts import PromptTemplate  
from langchain\_community.chat\_models import ChatOpenAI \# 可替换为 ChatVolcEngine  
from bioreport.ai.agent.tools import lookup\_gene\_function, statistical\_validator

class BioAgentV3:  
    def \_\_init\_\_(self, api\_key: str, base\_url: str \= "\[https://ark.cn-beijing.volces.com/api/v3\](https://ark.cn-beijing.volces.com/api/v3)"):  
        \# 1\. 初始化 LLM (Prefrontal Cortex)  
        \# 这里使用兼容 OpenAI 接口的火山引擎 Ark  
        self.llm \= ChatOpenAI(  
            model="doubao-pro-32k-240615",  
            api\_key=api\_key,  
            base\_url=base\_url,  
            temperature=0.1 \# 科学严谨性要求低温度  
        )  
          
        \# 2\. 挂载工具  
        self.tools \= \[lookup\_gene\_function, statistical\_validator\]  
          
        \# 3\. 定义学术级 System Prompt (The Persona)  
        \# 核心逻辑：Observation (看数据) \-\> Thought (想策略) \-\> Action (查库) \-\> Final Answer  
        template \= '''  
        You are an autonomous AI scientist specializing in Transcriptomics and Oncology.  
        Your goal is to interpret RNA-seq data to reveal drug resistance mechanisms.  
          
        CRITICAL RULES:  
        1\. \*\*Evidence-Based:\*\* You must use the \`lookup\_gene\_function\` tool to verify gene functions. Do not hallucinate.  
        2\. \*\*Logical Consistency:\*\* If data shows Gene A is UP, and the tool says Gene A promotes resistance, conclude "Resistance is enhanced".  
        3\. \*\*Citation:\*\* When you use knowledge from the tool, reference it.

        TOOLS AVAILABLE:  
        {tools}

        Use the following format for your reasoning loop:  
          
        Question: the input data/question  
        Thought: I need to analyze the top genes first.  
        Action: the action to take, should be one of \[{tool\_names}\]  
        Action Input: the input to the action  
        Observation: the result of the action  
        ... (repeat Thought/Action/Observation as needed)  
        Thought: I have sufficient evidence now.  
        Final Answer: The final academic report text.

        User Input: {input}  
        '''  
          
        self.prompt \= PromptTemplate.from\_template(template)  
          
        \# 4\. 构建 Agent  
        self.agent \= create\_react\_agent(self.llm, self.tools, self.prompt)  
        self.executor \= AgentExecutor(  
            agent=self.agent,   
            tools=self.tools,   
            verbose=True, \# 开启思考过程打印，这是写论文 Case Study 的绝佳素材  
            handle\_parsing\_errors=True,  
            max\_iterations=10 \# 防止死循环  
        )

    def run(self, input\_data: str):  
        """执行分析任务"""  
        return self.executor.invoke({"input": input\_data})

## **5\. 燃料系统：知识库构建脚本 (scripts/build\_knowledge\_base.py)**

这是你特别要求的\*\*“燃料”\*\*。没有这个，向量数据库就是空的。这个脚本负责将你的 CSV/PDF 灌入 ChromaDB。

import sys  
import os  
import pandas as pd  
\# 将项目根目录加入路径，以便导入模块  
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(\_\_file\_\_), '..')))

from bioreport.ai.rag.vector\_store import BioKnowledgeBase

def ingest\_csv\_knowledge(csv\_path: str):  
    """  
    将结构化的 CSV 知识表导入向量数据库  
    CSV 格式建议: symbol, function, pathway, drug\_sensitivity, paper\_ref  
    """  
    print(f"🚀 Starting ingestion from {csv\_path}...")  
      
    \# 1\. 读取数据  
    df \= pd.read\_csv(csv\_path)  
      
    documents \= \[\]  
    metadatas \= \[\]  
    ids \= \[\]  
      
    kb \= BioKnowledgeBase()  
      
    \# 2\. 遍历每一行，构建语义文档  
    for idx, row in df.iterrows():  
        \# 构建一段人类可读的文本，这是 Embedding 的基础  
        \# 技巧：将这就话写成类似摘要的形式，方便检索  
        doc\_text \= (  
            f"Gene Symbol: {row\['symbol'\]}. "  
            f"Function in Cancer: {row\['function'\]}. "  
            f"Pathway: {row\['pathway'\]}. "  
            f"Drug Sensitivity: {row\['drug\_sensitivity'\]}."  
        )  
          
        documents.append(doc\_text)  
          
        \# 元数据用于过滤 (Filter)  
        metadatas.append({  
            "symbol": row\['symbol'\],  
            "source": "Manual\_Curated\_List\_v1",  
            "ref": str(row.get('paper\_ref', 'N/A'))  
        })  
          
        \# 唯一 ID  
        ids.append(f"GENE\_{row\['symbol'\]}\_{idx}")  
          
    \# 3\. 批量写入  
    kb.add\_knowledge(documents, metadatas, ids)  
    print(f"✅ Successfully ingested {len(documents)} items into Bio-VectorDB.")

if \_\_name\_\_ \== "\_\_main\_\_":  
    \# 示例：运行脚本  
    \# python scripts/build\_knowledge\_base.py data/knowledge\_base/hcc\_driver\_genes.csv  
    if len(sys.argv) \> 1:  
        ingest\_csv\_knowledge(sys.argv\[1\])  
    else:  
        print("Please provide the path to the CSV file.")  
