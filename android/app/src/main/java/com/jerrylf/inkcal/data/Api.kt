package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.POST
import retrofit2.http.Query

/**
 * inkcal Flask API。端点按 docs/android-app-spec.md §6 逐个补。
 *
 * 路径不带前导 `/`：baseUrl 已由 [ServerUrl.normalize] 规范成以 `/` 结尾。
 */
interface InkcalApi {

  @GET("api/data-version")
  suspend fun dataVersion(): DataVersionDto

  @GET("api/dates")
  suspend fun dates(): List<String>

  @GET("api/records")
  suspend fun recordsOfDay(@Query("date") date: String): DayResponse

  @GET("api/records")
  suspend fun recordsInRange(
    @Query("start") start: String,
    @Query("end") end: String,
  ): RangeResponse

  @GET("api/settings")
  suspend fun settings(): SettingsDto

  @GET("api/decisions")
  suspend fun decisions(@Query("date") date: String): DecisionsResponse

  @POST("api/reanalyze")
  suspend fun reanalyze(@Body body: ReanalyzeRequest): ReanalyzeResponse

  /** DELETE 带 JSON body，Retrofit 的 @DELETE 不支持，得用 @HTTP。 */
  @HTTP(method = "DELETE", path = "api/record", hasBody = true)
  suspend fun deleteRecord(@Body body: DeleteRecordRequest): DeleteRecordResponse

  @POST("api/login")
  suspend fun login(@Body body: LoginRequest): OkDto

  @POST("api/logout")
  suspend fun logout(): OkDto
}

object ApiFactory {

  @OptIn(ExperimentalSerializationApi::class)
  val json: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    // 服务端是 snake_case（thumbnail_url / protein_g），DTO 写 camelCase
    namingStrategy = JsonNamingStrategy.SnakeCase
  }

  /** baseUrl 必须已规范化。 */
  fun create(baseUrl: String, client: OkHttpClient): InkcalApi =
    Retrofit.Builder()
      .baseUrl(baseUrl)
      .client(client)
      .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
      .build()
      .create(InkcalApi::class.java)
}
