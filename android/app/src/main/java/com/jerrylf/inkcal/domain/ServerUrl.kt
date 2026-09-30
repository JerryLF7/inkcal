package com.jerrylf.inkcal.domain

/**
 * 服务器地址规范化。纯函数，无 Android 依赖，单元测试覆盖。
 *
 * Retrofit 要求 baseUrl 以 `/` 结尾，用户不会主动敲，所以这里补齐。
 * 局域网访问常用 http://192.168.x.x:5800，不带 scheme 时按 http 补。
 */
object ServerUrl {

  /** 返回规范化后的地址；空串或只有空白时返回 null。 */
  fun normalize(input: String): String? {
    val trimmed = input.trim().trimEnd('/')
    if (trimmed.isEmpty()) return null
    val withScheme = when {
      trimmed.startsWith("http://") || trimmed.startsWith("https://") -> trimmed
      else -> "http://$trimmed"
    }
    return "$withScheme/"
  }
}
