package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.ToolCallDto
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 工具调用 → 过程层/产物层的翻译（spec §10）。
 *
 * 最该钉住的是产物分流：**本轮有写操作时，查询结果不出卡**。判据写错就会出现
 * 「说一句『记一根玉米，分量和昨天差不多』，屏幕上弹出三张卡」——查今天（查重）和
 * 昨天（份量参考）本来都是内部步骤。
 */
class ChatToolsTest {

  private fun tool(name: String, args: String = "{}", result: String? = "{}") =
    ToolCallDto(
      name = name,
      args = Json.parseToJsonElement(args) as JsonObject,
      result = result?.let { Json.parseToJsonElement(it) as JsonObject },
    )

  // ── 过程层 ─────────────────────────────────────────────────────

  @Test
  fun `步骤标题优先用 intent`() {
    val step = ChatTools.step(tool("get_records_in_range", """{"intent":"查询昨天午餐","start":"2026-10-01"}"""))
    assertEquals("查询昨天午餐", step.title)
  }

  @Test
  fun `没有 intent 时按工具名和参数兜底`() {
    assertEquals(
      "查询餐食记录 (10-01~10-02)",
      ChatTools.step(tool("get_records_in_range", """{"start":"2026-10-01","end":"2026-10-02"}""")).title,
    )
    assertEquals(
      "查询餐食记录 (10-01)",
      ChatTools.step(tool("get_records_in_range", """{"start":"2026-10-01"}""")).title,
    )
    assertEquals("统计摄入情况", ChatTools.step(tool("get_intake_stats")).title)
    assertEquals("搜索餐食记录「玉米」", ChatTools.step(tool("search_meals", """{"keyword":"玉米"}""")).title)
    assertEquals("查看 AI 识别决策 (10-01)", ChatTools.step(tool("get_decisions", """{"date":"2026-10-01"}""")).title)
    assertEquals("补记餐食记录", ChatTools.step(tool("add_record")).title)
  }

  @Test
  fun `参数展示剔除 intent，避免和标题重复`() {
    val step = ChatTools.step(tool("search_meals", """{"intent":"找玉米","keyword":"玉米"}"""))
    assertTrue(step.argsJson.contains("keyword"))
    assertFalse("intent 不该再出现", step.argsJson.contains("intent"))
  }

  @Test
  fun `步骤徽标`() {
    val records =
      tool("get_records_in_range", result = """{"ok":true,"records":[{"asset_id":"a"},{"asset_id":"b"}]}""")
    assertEquals("2 条", ChatTools.step(records).badge)

    // 0 条不显示徽标
    assertNull(ChatTools.step(tool("get_records_in_range", result = """{"ok":true,"records":[]}""")).badge)

    val stats = tool("get_intake_stats", result = """{"ok":true,"total":{"calories":1832.4}}""")
    assertEquals("1832 kcal", ChatTools.step(stats).badge)

    val decisions = tool("get_decisions", result = """{"ok":true,"count":7}""")
    assertEquals("7 条", ChatTools.step(decisions).badge)
  }

  @Test
  fun `结果摘要`() {
    assertEquals(
      "匹配 2 条记录",
      ChatTools.step(tool("search_meals", result = """{"ok":true,"records":[{},{}]}""")).summary,
    )
    assertEquals(
      "新增「水煮玉米」120 kcal",
      ChatTools.step(tool("add_record", result = """{"ok":true,"record":{"meal":"水煮玉米","calories":120}}""")).summary,
    )
    assertEquals(
      "「牛肉面」980 kcal",
      ChatTools.step(tool("edit_record", result = """{"ok":true,"after":{"meal":"牛肉面","calories":980}}""")).summary,
    )
    assertEquals(
      "已生成待确认删除卡",
      ChatTools.step(tool("request_delete_record", result = """{"ok":true,"confirm_card":{"asset_id":"x"}}""")).summary,
    )
    assertEquals("boom", ChatTools.step(tool("add_record", result = """{"ok":false,"error":"boom"}""")).summary)
  }

  // ── 产物层 ─────────────────────────────────────────────────────

  @Test
  fun `写操作本身始终出卡`() {
    val artifacts =
      ChatTools.artifacts(
        listOf(
          tool("add_record", result = """{"ok":true,"record":{"asset_id":"a","meal":"玉米","calories":120,"photo_time":"2026-10-02T15:00:00+08:00"}}"""),
          tool("edit_record", result = """{"ok":true,"after":{"asset_id":"b","meal":"面","calories":900,"photo_time":"2026-10-02T12:00:00+08:00"}}"""),
        )
      )
    assertEquals(listOf(ArtifactKind.ADDED, ArtifactKind.UPDATED), artifacts.map { it.kind })
  }

  @Test
  fun `本轮有写操作时，查询结果不出卡（防一次补记弹三张）`() {
    val log =
      listOf(
        tool("get_records_in_range", result = """{"ok":true,"records":[{"asset_id":"today"}]}"""),
        tool("get_records_in_range", result = """{"ok":true,"records":[{"asset_id":"yesterday"}]}"""),
        tool("add_record", result = """{"ok":true,"record":{"asset_id":"new","meal":"玉米","photo_time":"2026-10-02T15:00:00+08:00"}}"""),
      )
    val artifacts = ChatTools.artifacts(log)
    assertEquals(1, artifacts.size)
    assertEquals(ArtifactKind.ADDED, artifacts.single().kind)
  }

  @Test
  fun `没有写操作时，查询结果才出卡`() {
    val log =
      listOf(tool("get_records_in_range", result = """{"ok":true,"records":[{"asset_id":"a"},{"asset_id":"b"}]}"""))
    val artifacts = ChatTools.artifacts(log)
    assertEquals(ArtifactKind.RECORDS, artifacts.single().kind)
    assertEquals("找到 2 餐：", artifacts.single().title)
    assertEquals(2, artifacts.single().records.size)
  }

  @Test
  fun `搜索的标题带关键词`() {
    val log =
      listOf(
        tool(
          "search_meals",
          """{"keyword":"玉米"}""",
          """{"ok":true,"records":[{"asset_id":"a"}]}""",
        )
      )
    assertEquals("搜索「玉米」找到 1 餐：", ChatTools.artifacts(log).single().title)
  }

  @Test
  fun `统计卡读别名并兜底 0`() {
    // 后端同时给 meals/count 与 protein/protein_g 两套
    val log =
      listOf(
        tool(
          "get_intake_stats",
          result = """{"ok":true,"total":{"start":"2026-10-01","end":"2026-10-02","calories":1832,"count":3,"protein_g":88,"carbs_g":210,"fat_g":55}}""",
        )
      )
    val stats = ChatTools.artifacts(log).single().stats!!
    assertEquals(1832.0, stats.calories, 0.01)
    assertEquals(3, stats.meals)
    assertEquals(88.0, stats.protein, 0.01)
  }

  @Test
  fun `删除确认卡带出要删的 asset_id 与文案字段`() {
    val log =
      listOf(
        tool(
          "request_delete_record",
          result = """{"ok":true,"confirm_card":{"asset_id":"abc","meal":"牛肉面","photo_time":"2026-10-01T12:30:00+08:00","calories":980}}""",
        )
      )
    val card = ChatTools.artifacts(log).single()
    assertEquals(ArtifactKind.DELETE_CONFIRM, card.kind)
    assertEquals("abc", card.confirmAssetId)
    assertEquals("牛肉面", card.confirmMeal)
    assertEquals(980.0, card.confirmCalories, 0.01)
  }

  @Test
  fun `get_decisions 没有产物卡`() {
    assertTrue(ChatTools.artifacts(listOf(tool("get_decisions", result = """{"ok":true,"count":3}"""))).isEmpty())
  }

  @Test
  fun `失败的写操作不出卡`() {
    assertTrue(
      ChatTools.artifacts(listOf(tool("add_record", result = """{"ok":false,"error":"x"}"""))).isEmpty()
    )
  }

  // ── 记录归一化 ─────────────────────────────────────────────────

  @Test
  fun `工具返回的记录缺 photos 时用自身字段合成一张`() {
    val raw =
      com.jerrylf.inkcal.data.RecordDto(
        assetId = "a",
        photoTime = "2026-10-02T15:00:00+08:00",
        meal = "玉米",
        calories = 120.0,
      )
    val normalized = ChatTools.normalizeRecord(raw)
    assertEquals("2026-10-02", normalized.date)
    assertEquals("low", normalized.confidence)
    assertEquals(1, normalized.photos.size)
    assertEquals("a", normalized.photos.single().assetId)
    assertEquals("玉米", normalized.photos.single().meal)
  }

  @Test
  fun `成功写操作的判定`() {
    assertTrue(ChatTools.hasSuccessfulWrite(listOf(tool("add_record", result = """{"ok":true}"""))))
    assertFalse(ChatTools.hasSuccessfulWrite(listOf(tool("add_record", result = """{"ok":false}"""))))
    // 只查不写不算
    assertFalse(ChatTools.hasSuccessfulWrite(listOf(tool("get_records_in_range", result = """{"ok":true}"""))))
  }
}
