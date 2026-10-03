package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
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

  @PUT("api/settings")
  suspend fun updateSettings(@Body body: SettingsUpdateRequest): SettingsDto

  @GET("api/decisions")
  suspend fun decisions(@Query("date") date: String): DecisionsResponse

  /** 未处理的相册照片，按天分页。cursor 缺省今天，days 1–30。 */
  @GET("api/album-photos")
  suspend fun albumPhotos(
    @Query("cursor") cursor: String,
    @Query("days") days: Int,
  ): AlbumPhotosResponse

  /** 单张走旧契约、多张走 results/summary，见 [AnalyzeResponse]。 */
  @POST("api/analyze-album-photo")
  suspend fun analyzeAlbumPhoto(@Body body: AnalyzeRequest): AnalyzeResponse

  /** 本地上传：multipart，字段名必须是 image。 */
  @Multipart
  @POST("api/manual-upload")
  suspend fun manualUpload(@Part image: MultipartBody.Part): ManualUploadResponse

  /** 无 EXIF 时把已入库的记录挪到用户选的日期。 */
  @POST("api/move-record")
  suspend fun moveRecord(@Body body: MoveRecordRequest): MoveRecordResponse

  // ── Calo 聊天 ──────────────────────────────────────────────────

  @GET("api/chat/sessions")
  suspend fun chatSessions(): ChatSessionsResponse

  /** session_id 缺省或无效 = 最新会话；一条会话都没有时 session_id 为 null。 */
  @GET("api/chat/messages")
  suspend fun chatMessages(@Query("session_id") sessionId: Int? = null): ChatMessagesResponse

  /** 同步跑一轮 agent loop，非流式；超时给到 300 s。 */
  @POST("api/chat/send")
  suspend fun chatSend(@Body body: ChatSendRequest): ChatSendResponse

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
