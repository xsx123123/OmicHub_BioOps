import type { ConditionOperator, ConditionRule, FormValues } from '@/types/schema'

/**
 * 条件渲染评估器
 *
 * 与后端 omichub/domain/flow/condition.py 对齐，支持：
 * - 简单条件：field + operator + value
 * - 复合条件：and_rules / or_rules 嵌套
 */
export function useConditionEvaluator() {
  function evaluate(rule: ConditionRule | undefined, values: FormValues): boolean {
    if (!rule) {
      return true
    }

    // 复合条件：AND
    if (rule.and_rules && rule.and_rules.length > 0) {
      return rule.and_rules.every((r) => evaluate(r, values))
    }

    // 复合条件：OR
    if (rule.or_rules && rule.or_rules.length > 0) {
      return rule.or_rules.some((r) => evaluate(r, values))
    }

    // 简单条件
    if (rule.field && rule.operator) {
      const actual = values[rule.field]
      return compare(actual, rule.operator, rule.value)
    }

    return true
  }

  function compare(
    actual: unknown,
    operator: ConditionOperator,
    expected: unknown,
  ): boolean {
    switch (operator) {
      case 'eq':
        return actual === expected
      case 'ne':
        return actual !== expected
      case 'gt':
        return Number(actual) > Number(expected)
      case 'lt':
        return Number(actual) < Number(expected)
      case 'gte':
        return Number(actual) >= Number(expected)
      case 'lte':
        return Number(actual) <= Number(expected)
      case 'in':
        return Array.isArray(expected) && expected.includes(actual)
      case 'not_in':
        return Array.isArray(expected) && !expected.includes(actual)
      case 'contains':
        if (typeof actual === 'string' && typeof expected === 'string') {
          return actual.includes(expected)
        }
        if (Array.isArray(actual)) {
          return actual.includes(expected)
        }
        return false
      case 'exists':
        return actual !== undefined && actual !== null && actual !== ''
      case 'regex':
        if (typeof actual !== 'string' || typeof expected !== 'string') {
          return false
        }
        return new RegExp(expected).test(actual)
      default:
        return true
    }
  }

  return { evaluate }
}
