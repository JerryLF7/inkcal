package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Calo 的回答大量是「一行一条」的清单，解析错了聊天就没法看。 */
class MarkdownTextTest {

  @Test
  fun `每行自成一段（硬换行），与网页版一致`() {
    val blocks = MarkdownText.parse("第一行\n第二行")
    assertEquals(2, blocks.size)
    assertEquals("第一行", (blocks[0] as MdBlock.Paragraph).spans.single().text)
    assertEquals("第二行", (blocks[1] as MdBlock.Paragraph).spans.single().text)
  }

  @Test
  fun `无序列表与有序列表都当条目`() {
    val blocks = MarkdownText.parse("- 约 230 千卡\n1. 蛋白质 19g\n+ 碳水 2g")
    assertTrue(blocks.all { it is MdBlock.Bullet })
    assertEquals("约 230 千卡", (blocks[0] as MdBlock.Bullet).spans.single().text)
    assertEquals("蛋白质 19g", (blocks[1] as MdBlock.Bullet).spans.single().text)
    assertEquals("碳水 2g", (blocks[2] as MdBlock.Bullet).spans.single().text)
  }

  @Test
  fun `标题按井号数分级`() {
    val blocks = MarkdownText.parse("# 一级\n### 三级")
    assertEquals(1, (blocks[0] as MdBlock.Heading).level)
    assertEquals(3, (blocks[1] as MdBlock.Heading).level)
  }

  @Test
  fun `围栏代码块整体保留，不按行拆`() {
    val blocks = MarkdownText.parse("前\n```\nline1\nline2\n```\n后")
    assertEquals(3, blocks.size)
    assertEquals("line1\nline2", (blocks[1] as MdBlock.Code).text)
  }

  @Test
  fun `没闭合的代码块也不吞内容`() {
    val blocks = MarkdownText.parse("```\n孤立内容")
    assertEquals(1, blocks.size)
    assertEquals("孤立内容", (blocks[0] as MdBlock.Code).text)
  }

  @Test
  fun `引用`() {
    val blocks = MarkdownText.parse("> 今天摄入了多少")
    assertEquals("今天摄入了多少", (blocks[0] as MdBlock.Quote).spans.single().text)
  }

  @Test
  fun `行内粗体与代码`() {
    val spans = MarkdownText.inline("吃了 **两碗** 饭和 `代码`")
    assertEquals("吃了 ", spans[0].text)
    assertEquals("两碗", spans[1].text)
    assertTrue(spans[1].bold)
    assertEquals(" 饭和 ", spans[2].text)
    assertEquals("代码", spans[3].text)
    assertTrue(spans[3].code)
  }

  @Test
  fun `双星号优先于单星号，不会被拆成两个斜体`() {
    val spans = MarkdownText.inline("**重点**")
    assertEquals(1, spans.size)
    assertTrue(spans[0].bold)
    assertEquals("重点", spans[0].text)
  }

  @Test
  fun `链接取出文本与地址`() {
    val spans = MarkdownText.inline("见 [文档](https://example.com)")
    assertEquals("见 ", spans[0].text)
    assertEquals("文档", spans[1].text)
    assertEquals("https://example.com", spans[1].link)
  }

  @Test
  fun `孤立的星号按普通字符处理，不吞字`() {
    val spans = MarkdownText.inline("2 * 3 = 6")
    assertEquals("2 * 3 = 6", spans.joinToString("") { it.text })
  }

  @Test
  fun `空输入不炸`() {
    assertTrue(MarkdownText.parse("").isEmpty())
    assertEquals("", MarkdownText.inline("").joinToString("") { it.text })
  }
}
