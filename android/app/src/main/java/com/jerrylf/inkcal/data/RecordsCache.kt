package com.jerrylf.inkcal.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import java.io.File

/**
 * 已加载记录的磁盘缓存。
 *
 * 目的是冷启动立刻有内容可看，再在后台重新拉取覆盖（stale-while-revalidate）——
 * 不做"缓存优先、过期才请求"那套，因为服务端 cron 会随时写新记录，缓存永远不可信。
 *
 * payload 里带 baseUrl：换了服务器就不认旧缓存，避免把上一台服务器的饮食记录
 * 显示在新服务器上（也顺带避免明文留在磁盘上被误读）。
 */
@Serializable
data class RecordsCachePayload(
  val baseUrl: String,
  val records: List<RecordDto>,
  val burns: Map<String, BurnDto>,
  /** 已经加载到的最早日期，用来接着往下翻。 */
  val earliest: String,
  val atEnd: Boolean,
)

class RecordsCache(dir: File) {

  private val file = File(dir, CACHE_FILE)

  suspend fun read(baseUrl: String): RecordsCachePayload? =
    withContext(Dispatchers.IO) {
      // 读缓存永远不能把 App 拖崩：文件损坏、格式变了都当作没有缓存
      runCatching {
        if (baseUrl.isBlank() || !file.exists()) return@runCatching null
        ApiFactory.json
          .decodeFromString<RecordsCachePayload>(file.readText())
          .takeIf { it.baseUrl == baseUrl }
      }.getOrNull()
    }

  suspend fun write(payload: RecordsCachePayload) {
    withContext(Dispatchers.IO) {
      runCatching {
        val tmp = File(file.parentFile, "$CACHE_FILE.tmp")
        tmp.writeText(ApiFactory.json.encodeToString(payload))
        // 先写临时文件再改名，避免写到一半被杀留下半个 JSON
        if (!tmp.renameTo(file)) {
          file.delete()
          tmp.renameTo(file)
        }
      }
    }
  }

  suspend fun clear() {
    withContext(Dispatchers.IO) { runCatching { file.delete() } }
  }

  private companion object {
    const val CACHE_FILE = "records-cache.json"
  }
}
