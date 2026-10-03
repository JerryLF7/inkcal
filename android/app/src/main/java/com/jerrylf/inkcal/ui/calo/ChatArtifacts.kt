package com.jerrylf.inkcal.ui.calo

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.jerrylf.inkcal.data.ChatMessageDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.ArtifactKind
import com.jerrylf.inkcal.domain.ChatTools
import com.jerrylf.inkcal.domain.MdBlock
import com.jerrylf.inkcal.domain.MarkdownText
import com.jerrylf.inkcal.domain.ToolArtifact
import com.jerrylf.inkcal.domain.ToolStep
import com.jerrylf.inkcal.ui.records.MealCard
import kotlin.math.roundToInt

/** 链接色，与网页版一致。 */
private val LinkBlue = Color(0xFF5B8DEF)

/**
 * 一条 assistant 消息的渲染，对应 spec §10 的「过程层 + 产物层 + 正文」三段式。
 *
 * 过程层默认折叠；产物层只渲染该出的卡（规则在 [ChatTools.artifacts]）。
 */
@Composable
fun AssistantMessage(
  message: ChatMessageDto,
  baseUrl: String,
  deleteState: DeleteState?,
  deleting: Boolean,
  onOpenRecord: (RecordDto) -> Unit,
  onConfirmDelete: () -> Unit,
  onCancelDelete: () -> Unit,
) {
  val steps = remember(message) { message.toolLog.map(ChatTools::step) }
  val artifacts = remember(message) { ChatTools.artifacts(message.toolLog) }

  Column(
    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    verticalArrangement = Arrangement.spacedBy(6.dp),
  ) {
    if (steps.isNotEmpty()) {
      ToolStepsBlock(steps)
    }

    artifacts.forEach { artifact ->
      when (artifact.kind) {
        ArtifactKind.STATS -> StatsCard(artifact)
        ArtifactKind.DELETE_CONFIRM ->
          DeleteConfirmCard(
            artifact = artifact,
            state = deleteState,
            deleting = deleting,
            onConfirm = onConfirmDelete,
            onCancel = onCancelDelete,
          )
        ArtifactKind.RECORDS ->
          ArtifactRecords(artifact.title, artifact.records, baseUrl, onOpenRecord)
        else ->
          artifact.record?.let {
            ArtifactRecords(artifact.title, listOf(it), baseUrl, onOpenRecord)
          }
      }
    }

    if (message.content.isNotBlank()) {
      Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(12.dp),
      ) {
        MarkdownText2(message.content, Modifier.padding(10.dp))
      }
    }
  }
}

/** 过程层：默认折叠的步骤链。 */
@Composable
private fun ToolStepsBlock(steps: List<ToolStep>) {
  var expanded by remember { mutableStateOf(false) }

  Surface(
    color = MaterialTheme.colorScheme.surface,
    shape = RoundedCornerShape(8.dp),
    tonalElevation = 1.dp,
  ) {
    Column(modifier = Modifier.fillMaxWidth()) {
      TextButton(onClick = { expanded = !expanded }) {
        Text(if (expanded) "已执行 ${steps.size} 步操作 ▴" else "已执行 ${steps.size} 步操作 ▾")
      }
      if (expanded) {
        Column(
          modifier = Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, bottom = 8.dp),
          verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
          steps.forEach { StepRow(it) }
        }
      }
    }
  }
}

@Composable
private fun StepRow(step: ToolStep) {
  var expanded by remember { mutableStateOf(false) }

  Column(modifier = Modifier.fillMaxWidth()) {
    Row(
      modifier = Modifier.fillMaxWidth(),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      Text(if (step.ok) "✓" else "✗", style = MaterialTheme.typography.labelMedium)
      Text(
        text = step.title,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier.weight(1f),
      )
      step.badge?.let {
        Text(
          text = it,
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
      }
      TextButton(onClick = { expanded = !expanded }) {
        Text(if (expanded) "收起" else "详情", style = MaterialTheme.typography.labelSmall)
      }
    }
    if (expanded) {
      Column(modifier = Modifier.padding(start = 20.dp, bottom = 6.dp)) {
        Text(
          text = step.argsJson,
          style = MaterialTheme.typography.labelSmall,
          fontFamily = FontFamily.Monospace,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(text = step.summary, style = MaterialTheme.typography.labelSmall)
      }
    }
  }
}

/** 产物：一批餐卡。 */
@Composable
private fun ArtifactRecords(
  title: String,
  records: List<RecordDto>,
  baseUrl: String,
  onOpenRecord: (RecordDto) -> Unit,
) {
  Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
    if (title.isNotBlank()) Text(title, style = MaterialTheme.typography.labelLarge)
    records.forEach { record ->
      MealCard(
        record = record,
        baseUrl = baseUrl,
        hasDecision = false,
        onClick = { onOpenRecord(record) },
      )
    }
  }
}

/** 产物：摄入汇总卡。 */
@Composable
private fun StatsCard(artifact: ToolArtifact) {
  val stats = artifact.stats ?: return
  Card(modifier = Modifier.fillMaxWidth()) {
    Column(
      modifier = Modifier.padding(12.dp),
      verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
      Text(artifact.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
      HorizontalDivider()
      Row(modifier = Modifier.fillMaxWidth()) {
        StatCell("总热量", "${stats.calories.roundToInt()}", "kcal", Modifier.weight(1f))
        StatCell("餐数", "${stats.meals}", "", Modifier.weight(1f))
      }
      Row(modifier = Modifier.fillMaxWidth()) {
        StatCell("蛋白质", "${stats.protein.roundToInt()}", "g", Modifier.weight(1f))
        StatCell("碳水", "${stats.carbs.roundToInt()}", "g", Modifier.weight(1f))
        StatCell("脂肪", "${stats.fat.roundToInt()}", "g", Modifier.weight(1f))
      }
    }
  }
}

@Composable
private fun StatCell(label: String, value: String, unit: String, modifier: Modifier = Modifier) {
  Column(modifier = modifier) {
    Text(
      text = label,
      style = MaterialTheme.typography.labelSmall,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Row(verticalAlignment = Alignment.Bottom) {
      Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
      if (unit.isNotEmpty()) {
        Text(" $unit", style = MaterialTheme.typography.labelSmall)
      }
    }
  }
}

/**
 * 删除确认卡（AGENTS §4 的安全契约）。
 *
 * 状态只存本地：历史消息重开时重新显示为待确认，和网页版一致，**不要持久化**。
 * 模型给的东西（tool_log）绝不能触发删除，只有这里的按钮会。
 */
@Composable
private fun DeleteConfirmCard(
  artifact: ToolArtifact,
  state: DeleteState?,
  deleting: Boolean,
  onConfirm: () -> Unit,
  onCancel: () -> Unit,
) {
  val time = artifact.confirmTime.takeIf { it.length >= 16 }?.substring(11, 16).orEmpty()
  val label = artifact.confirmMeal.ifBlank { "该餐" }

  Card(
    modifier = Modifier.fillMaxWidth(),
    colors =
      androidx.compose.material3.CardDefaults.cardColors(
        containerColor = MaterialTheme.colorScheme.errorContainer
      ),
  ) {
    Column(
      modifier = Modifier.padding(12.dp),
      verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      when (state) {
        DeleteState.CONFIRMED -> Text("已删除该餐记录", style = MaterialTheme.typography.bodyMedium)
        DeleteState.CANCELLED -> Text("已取消删除", style = MaterialTheme.typography.bodyMedium)
        else -> {
          Text(
            text =
              "确认删除 $label" +
                (if (time.isNotEmpty()) "（$time，" else "（") +
                "${artifact.confirmCalories.roundToInt()} kcal）吗？",
            style = MaterialTheme.typography.bodyMedium,
          )
          Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
              onClick = onConfirm,
              enabled = !deleting,
              colors =
                androidx.compose.material3.ButtonDefaults.buttonColors(
                  containerColor = MaterialTheme.colorScheme.error
                ),
            ) {
              Text(if (deleting) "删除中…" else "确认删除")
            }
            OutlinedButton(onClick = onCancel, enabled = !deleting) { Text("取消") }
          }
        }
      }
    }
  }
}

/** 把 domain 解析出的块渲染成 Compose 文本。 */
@Composable
private fun MarkdownText2(source: String, modifier: Modifier = Modifier) {
  val blocks = remember(source) { MarkdownText.parse(source) }
  Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
    blocks.forEach { block ->
      when (block) {
        is MdBlock.Heading ->
          Text(
            text = annotated(block.spans),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
          )
        is MdBlock.Code ->
          Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.fillMaxWidth(),
          ) {
            Text(
              text = block.text,
              style = MaterialTheme.typography.labelSmall,
              fontFamily = FontFamily.Monospace,
              modifier = Modifier.padding(8.dp),
            )
          }
        is MdBlock.Quote ->
          Row(modifier = Modifier.fillMaxWidth()) {
            Box(
              modifier =
                Modifier.size(width = 3.dp, height = 16.dp)
                  .background(MaterialTheme.colorScheme.outline)
            )
            Text(
              text = annotated(block.spans),
              style = MaterialTheme.typography.bodyMedium,
              modifier = Modifier.padding(start = 8.dp),
            )
          }
        is MdBlock.Bullet ->
          Row(modifier = Modifier.fillMaxWidth()) {
            Text("• ", style = MaterialTheme.typography.bodyMedium)
            Text(text = annotated(block.spans), style = MaterialTheme.typography.bodyMedium)
          }
        is MdBlock.Paragraph ->
          Text(text = annotated(block.spans), style = MaterialTheme.typography.bodyMedium)
      }
    }
  }
}

@Composable
private fun annotated(spans: List<com.jerrylf.inkcal.domain.MdSpan>) = buildAnnotatedString {
  spans.forEach { span ->
    val link = span.link
    if (link != null) {
      // withLink 让基础 Text 自己处理点击（走 LocalUriHandler 打开浏览器），
      // 只上色不加 link 的话是条点不动的死链。
      withLink(
        LinkAnnotation.Url(
          url = link,
          styles = TextLinkStyles(style = SpanStyle(color = LinkBlue)),
        )
      ) {
        append(span.text)
      }
      return@forEach
    }
    val style =
      SpanStyle(
        fontWeight = if (span.bold) FontWeight.Bold else null,
        fontStyle = if (span.italic) androidx.compose.ui.text.font.FontStyle.Italic else null,
        fontFamily = if (span.code) FontFamily.Monospace else null,
      )
    withStyle(style) { append(span.text) }
  }
}
