package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

/**
 * inkcal Flask API。一期只用到这几个端点，其余按 docs/android-app-spec.md §6 逐个添加。
 *
 * 路径不带前导 `/`：baseUrl 已规范化成以 `/` 结尾。
 */
interface InkcalApi {

  @GET("api/data-version")
  suspend fun dataVersion(): DataVersionDto

  @POST("api/login")
  suspend fun login(@Body body: LoginRequest): OkDto

  @POST("api/logout")
  suspend fun logout(): OkDto
}

object ApiFactory {

  val json: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
  }

  /** baseUrl 必须是 [ServerUrl.normalize] 过的形式。 */
  fun create(baseUrl: String, client: OkHttpClient): InkcalApi =
    Retrofit.Builder()
      .baseUrl(baseUrl)
      .client(client)
      .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
      .build()
      .create(InkcalApi::class.java)
}
