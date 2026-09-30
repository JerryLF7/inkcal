package com.jerrylf.inkcal.data

import kotlinx.serialization.Serializable

/** 字段都可能缺省，DTO 一律给默认值；解析器开了 ignoreUnknownKeys。 */

@Serializable
data class DataVersionDto(
  val version: String = "",
  val pending: Int = 0,
)

@Serializable
data class LoginRequest(
  val user: String,
  /** 服务端字段名是 password，不是 pass。 */
  val password: String,
)

@Serializable
data class OkDto(val ok: Boolean = false)
