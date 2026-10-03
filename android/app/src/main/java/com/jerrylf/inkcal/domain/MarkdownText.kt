package com.jerrylf.inkcal.domain

/** 一段行内样式。 */
data class MdSpan(
  val text: String,
  val bold: Boolean = false,
  val italic: Boolean = false,
  val code: Boolean = false,
  val link: String? = null,
)

/** 块级结构。刻意不产出 Compose 的 AnnotatedString，domain 要保持纯 Kotlin 可测。 */
sealed interface MdBlock {
  data class Paragraph(val spans: List<MdSpan>) : MdBlock
  data class Bullet(val spans: List<MdSpan>) : MdBlock
  data class Heading(val level: Int, val spans: List<MdSpan>) : MdBlock
  data class Quote(val spans: List<MdSpan>) : MdBlock
  data class Code(val text: String) : MdBlock
}

/**
 * assistant 气泡的 Markdown 解析（**子集**，不是完整实现）。
 *
 * 覆盖实际会出现的：段落、粗体/斜体、行内代码、围栏代码块、无序/有序列表、引用、链接。
 * 表格、嵌套列表、脚注这些后端不会输出，不做。
 *
 * 换行按**硬换行**处理（每行自成一段），与网页版一致——Calo 的回答大量是
 * 「一行一条」的清单，软换行合并会把它们挤成一坨。
 */
object MarkdownText {

  fun parse(source: String): List<MdBlock> {
    val blocks = mutableListOf<MdBlock>()
    val codeBuffer = mutableListOf<String>()
    var inCode = false

    for (raw in source.replace("\r\n", "\n").split("\n")) {
      val line = raw.trimEnd()

      if (line.trimStart().startsWith("```")) {
        if (inCode) {
          blocks += MdBlock.Code(codeBuffer.joinToString("\n"))
          codeBuffer.clear()
        }
        inCode = !inCode
        continue
      }
      if (inCode) {
        codeBuffer += raw
        continue
      }
      if (line.isBlank()) continue

      val trimmed = line.trimStart()
      when {
        trimmed.startsWith("#") -> {
          val level = trimmed.takeWhile { it == '#' }.length.coerceAtMost(6)
          blocks += MdBlock.Heading(level, inline(trimmed.drop(level).trim()))
        }
        trimmed.startsWith("> ") -> blocks += MdBlock.Quote(inline(trimmed.removePrefix("> ")))
        // 注意用 containsMatchIn：Regex.matches 要求**整个字符串**匹配，
        // 而这里只锚了行首的项目符号，用 matches 会永远判不出列表。
        BULLET.containsMatchIn(trimmed) ->
          blocks += MdBlock.Bullet(inline(BULLET.replaceFirst(trimmed, "").trim()))
        else -> blocks += MdBlock.Paragraph(inline(trimmed))
      }
    }
    // 没闭合的代码块也要吐出来，别把内容吞掉
    if (inCode && codeBuffer.isNotEmpty()) blocks += MdBlock.Code(codeBuffer.joinToString("\n"))
    return blocks
  }

  private val BULLET = Regex("""^([-*+]|\d+\.)\s+""")

  /** 行内扫描：** 优先于 *，避免 `**a**` 被当成两个斜体。 */
  internal fun inline(text: String): List<MdSpan> {
    val spans = mutableListOf<MdSpan>()
    val plain = StringBuilder()
    var i = 0

    fun flush() {
      if (plain.isNotEmpty()) {
        spans += MdSpan(plain.toString())
        plain.clear()
      }
    }

    while (i < text.length) {
      val rest = text.substring(i)
      when {
        rest.startsWith("**") -> {
          val end = text.indexOf("**", i + 2)
          if (end > 0) {
            flush()
            spans += MdSpan(text.substring(i + 2, end), bold = true)
            i = end + 2
          } else {
            plain.append(text[i]); i++
          }
        }
        rest.startsWith("`") -> {
          val end = text.indexOf('`', i + 1)
          if (end > 0) {
            flush()
            spans += MdSpan(text.substring(i + 1, end), code = true)
            i = end + 1
          } else {
            plain.append(text[i]); i++
          }
        }
        rest.startsWith("[") -> {
          val close = text.indexOf("](", i)
          val end = if (close > 0) text.indexOf(')', close) else -1
          if (close > 0 && end > close) {
            flush()
            spans += MdSpan(text.substring(i + 1, close), link = text.substring(close + 2, end))
            i = end + 1
          } else {
            plain.append(text[i]); i++
          }
        }
        rest.startsWith("*") || rest.startsWith("_") -> {
          val marker = text[i]
          val end = text.indexOf(marker, i + 1)
          if (end > i + 1) {
            flush()
            spans += MdSpan(text.substring(i + 1, end), italic = true)
            i = end + 1
          } else {
            plain.append(text[i]); i++
          }
        }
        else -> {
          plain.append(text[i]); i++
        }
      }
    }
    flush()
    return spans.ifEmpty { listOf(MdSpan(text)) }
  }
}
