package com.jerrylf.inkcal.data

import java.nio.file.Files
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 缓存是冷启动体验的关键，也是最容易被"半个 JSON""换服务器串数据"坑到的地方。
 * 这里用临时目录跑，不依赖 Android。
 */
class RecordsCacheTest {

  private fun tempCache(): RecordsCache =
    RecordsCache(Files.createTempDirectory("inkcal-cache").toFile())

  private fun payload(baseUrl: String, assetId: String = "a1") =
    RecordsCachePayload(
      baseUrl = baseUrl,
      records = listOf(RecordDto(assetId = assetId, photoTime = "2026-10-01T12:00:00+08:00", calories = 500.0)),
      burns = mapOf("2026-10-01" to BurnDto(date = "2026-10-01", activeKcal = 1092.0, steps = 16263)),
      earliest = "2026-09-25",
      atEnd = false,
    )

  @Test
  fun `写进去能原样读回来`() = runBlocking {
    val cache = tempCache()
    cache.write(payload("http://nuc:5800/"))

    val back = cache.read("http://nuc:5800/")!!
    assertEquals("a1", back.records.single().assetId)
    assertEquals(500.0, back.records.single().calories, 0.001)
    assertEquals(1092.0, back.burns["2026-10-01"]!!.activeKcal, 0.001)
    assertEquals("2026-09-25", back.earliest)
    assertFalse(back.atEnd)
  }

  @Test
  fun `换了服务器不认旧缓存`() = runBlocking {
    val cache = tempCache()
    cache.write(payload("http://nuc:5800/"))
    assertNull(cache.read("http://other:5800/"))
  }

  @Test
  fun `没写过返回 null`() = runBlocking {
    assertNull(tempCache().read("http://nuc:5800/"))
  }

  @Test
  fun `缓存文件损坏时当作没有，不抛异常`() = runBlocking {
    val dir = Files.createTempDirectory("inkcal-cache").toFile()
    dir.resolve("records-cache.json").writeText("{ 这不是 JSON")
    assertNull(RecordsCache(dir).read("http://nuc:5800/"))
  }

  @Test
  fun `clear 之后读不到`() = runBlocking {
    val cache = tempCache()
    cache.write(payload("http://nuc:5800/"))
    cache.clear()
    assertNull(cache.read("http://nuc:5800/"))
  }

  @Test
  fun `空 baseUrl 不读也不写`() = runBlocking {
    val cache = tempCache()
    assertNull(cache.read(""))
    cache.write(payload(""))
    assertNull(cache.read(""))
  }

  @Test
  fun `覆盖写只保留最新一份`() = runBlocking {
    val cache = tempCache()
    cache.write(payload("http://nuc:5800/", assetId = "old"))
    cache.write(payload("http://nuc:5800/", assetId = "new"))

    val back = cache.read("http://nuc:5800/")!!
    assertEquals(1, back.records.size)
    assertEquals("new", back.records.single().assetId)
    assertTrue(back.records.none { it.assetId == "old" })
  }
}
