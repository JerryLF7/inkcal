package com.jerrylf.inkcal.domain

import java.time.LocalDate

/**
 * 体征输入的客户端校验。范围必须与服务端 `web/server.py::api_settings` 一致：
 * 身高 50–260、体重 20–300、生日 YYYY-MM-DD。服务端越界直接 400，所以这里先挡住，
 * 免得用户敲完才被拒。
 *
 * 返回 null 表示通过；空串也算通过——留空即「这次不改这一项」（服务端只处理出现的键）。
 */
object BodyMetrics {

  fun heightError(raw: String): String? {
    val text = raw.trim()
    if (text.isEmpty()) return null
    val value = text.toDoubleOrNull() ?: return "身高要填数字"
    return if (value < 50 || value > 260) "身高需在 50–260 cm" else null
  }

  fun weightError(raw: String): String? {
    val text = raw.trim()
    if (text.isEmpty()) return null
    val value = text.toDoubleOrNull() ?: return "体重要填数字"
    return if (value < 20 || value > 300) "体重需在 20–300 kg" else null
  }

  fun birthdateError(raw: String): String? {
    val text = raw.trim()
    if (text.isEmpty()) return null
    val date = runCatching { LocalDate.parse(text) }.getOrNull() ?: return "生日格式应为 YYYY-MM-DD"
    return if (date.isAfter(LocalDate.now())) "生日不能是未来" else null
  }

  /** 四项里任一不合法就返回第一条错误，供保存按钮禁用与提示。 */
  fun firstError(height: String, weight: String, birthdate: String): String? =
    heightError(height) ?: weightError(weight) ?: birthdateError(birthdate)
}
