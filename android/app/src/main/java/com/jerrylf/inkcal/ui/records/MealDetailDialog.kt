package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.compose.AsyncImage
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.Decisions
import com.jerrylf.inkcal.domain.ImageUrl
import com.jerrylf.inkcal.domain.MealGrouping
import com.jerrylf.inkcal.domain.TimeFmt
import com.jerrylf.inkcal.theme.MacroCarbs
import com.jerrylf.inkcal.theme.MacroFat
import com.jerrylf.inkcal.theme.MacroProtein
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/** 两步确认的自动还原时间。 */
private const val ARM_TIMEOUT_MS = 3_000L

/** 重新分析的修正说明占位文案，详情页与长按菜单的表单共用。 */
internal const val REANALYZE_PLACEHOLDER = "修正说明，例：米饭只吃了一半 / 其实是玉米猪肉馅"

/** P/C/F 行，配色与网页端一致。详情页主行与照片分行共用。 */
@Composable
private fun MacroText(p: Double, c: Double, f: Double, style: TextStyle) {
  Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
    Text(text = "P${p.roundToInt()}", style = style, color = MacroProtein)
    Text(text = "C${c.roundToInt()}", style = style, color = MacroCarbs)
    Text(text = "F${f.roundToInt()}", style = style, color = MacroFat)
  }
}

/**
 * 餐卡详情，对应 docs/android-app-spec.md §8.4。
 *
 * 用全屏 Dialog 而不是 Nav3 路由：它渲染的数据**就来自列表状态**（按 asset_id 查出来），
 * 所以删除/重分析之后列表一重拉，详情自动跟着更新，不需要再维护一份副本。
 * 组被删光时外面会把 anchor 置空，这个组件随之消失。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MealDetailDialog(
  record: RecordDto,
  baseUrl: String,
  decisions: List<DecisionDto>,
  busy: Boolean,
  onClose: () -> Unit,
  onDeleteMeal: () -> Unit,
  onDeletePhoto: (String) -> Unit,
  onReanalyze: (String) -> Unit,
) {
  val photos = remember(record) { MealGrouping.sortedPhotos(record) }
  val pagerState = rememberPagerState(pageCount = { photos.size })
  val scope = rememberCoroutineScope()
  val goToPage: (Int) -> Unit = { index -> scope.launch { pagerState.animateScrollToPage(index) } }

  // 缩放状态跟着当前页走，翻页就复位
  var scale by remember { mutableFloatStateOf(1f) }
  var offset by remember { mutableStateOf(Offset.Zero) }
  LaunchedEffect(pagerState.currentPage) {
    scale = 1f
    offset = Offset.Zero
  }

  var showForm by remember { mutableStateOf(false) }
  var notes by remember { mutableStateOf("") }

  // 两个删除入口各自独立的武装态，互不干扰
  var mealArmed by remember { mutableStateOf(false) }
  var photoArmedId by remember { mutableStateOf<String?>(null) }
  LaunchedEffect(mealArmed) {
    if (mealArmed) {
      delay(ARM_TIMEOUT_MS)
      mealArmed = false
    }
  }
  LaunchedEffect(photoArmedId) {
    if (photoArmedId != null) {
      delay(ARM_TIMEOUT_MS)
      photoArmedId = null
    }
  }

  // 纯文本补录没有图，后端恒 502，所以不给入口
  val canReanalyze =
    photos.any { it.thumbnailUrl.isNotBlank() } || record.replacementImage.isNotBlank()

  Dialog(
    onDismissRequest = onClose,
    properties = DialogProperties(usePlatformDefaultWidth = false),
  ) {
    Surface(modifier = Modifier.fillMaxSize()) {
      Column(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Row(
          modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp),
          verticalAlignment = Alignment.CenterVertically,
        ) {
          Text(
            text = record.meal.ifBlank { "未命名" },
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.weight(1f),
          )
          IconButton(onClick = onClose) {
            Icon(Icons.Filled.Close, contentDescription = "关闭")
          }
        }

        // 大图 + 多图翻页
        Box(
          modifier =
            Modifier.fillMaxWidth()
              .aspectRatio(4f / 3f)
              .background(MaterialTheme.colorScheme.surfaceVariant),
          contentAlignment = Alignment.Center,
        ) {
          if (photos.none { photoFullUrl(baseUrl, it, record) != null }) {
            Text(
              text = record.emoji.ifBlank { "🍽️" },
              style = MaterialTheme.typography.displaySmall,
            )
          } else {
            HorizontalPager(
              state = pagerState,
              // 放大之后把手势让给平移，否则缩放和翻页互相抢
              userScrollEnabled = scale <= 1.01f,
              modifier = Modifier.fillMaxSize(),
            ) { page ->
              AsyncImage(
                model = photoFullUrl(baseUrl, photos[page], record),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier =
                  Modifier.fillMaxSize()
                    .pointerInput(pagerState.currentPage) {
                      detectTransformGestures { _, pan, zoom, _ ->
                        val next = (scale * zoom).coerceIn(1f, 5f)
                        scale = next
                        offset = if (next > 1f) offset + pan else Offset.Zero
                      }
                    }
                    .graphicsLayer(
                      scaleX = scale,
                      scaleY = scale,
                      translationX = offset.x,
                      translationY = offset.y,
                    ),
              )
            }
          }

          if (photos.size > 1) {
            Surface(
              color = MaterialTheme.colorScheme.surface.copy(alpha = 0.75f),
              shape = RoundedCornerShape(12.dp),
              modifier = Modifier.align(Alignment.BottomEnd).padding(8.dp),
            ) {
              Text(
                text = "${pagerState.currentPage + 1} / ${photos.size}",
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
              )
            }
          }
        }

        // 缩略图条
        if (photos.size > 1) {
          LazyRow(
            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
          ) {
            itemsIndexed(photos, key = { _, photo -> photo.assetId }) { index, photo ->
              val selected = index == pagerState.currentPage
              AsyncImage(
                model = ImageUrl.thumbnail(baseUrl, photo.thumbnailUrl),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier =
                  Modifier.size(52.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .then(
                      if (selected) {
                        Modifier.border(
                          width = 2.dp,
                          color = MaterialTheme.colorScheme.primary,
                          shape = RoundedCornerShape(6.dp),
                        )
                      } else {
                        Modifier
                      }
                    )
                    .clickable { goToPage(index) },
              )
            }
          }
        }

        Column(
          modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
          verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
          Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
              text = "${record.calories.roundToInt()} kcal",
              style = MaterialTheme.typography.headlineSmall,
              fontWeight = FontWeight.SemiBold,
            )
            if (record.proteinG > 0 || record.carbsG > 0 || record.fatG > 0) {
              Spacer(modifier = Modifier.width(12.dp))
              MacroText(
                p = record.proteinG,
                c = record.carbsG,
                f = record.fatG,
                style = MaterialTheme.typography.labelMedium,
              )
            }
          }
          if (record.mealDetail.isNotBlank()) {
            Text(text = record.mealDetail, style = MaterialTheme.typography.bodyMedium)
          }
          Text(
            text =
              listOf(
                  TimeFmt.detailTime(record.photoTime),
                  sourceLabel(record),
                  confidenceLabel(record.confidence),
                )
                .filter { it.isNotBlank() }
                .joinToString(" · "),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )

          // 多图组才展示逐张明细
          if (photos.size > 1) {
            HorizontalDivider()
            Text("照片明细", style = MaterialTheme.typography.titleSmall)
            photos.forEachIndexed { index, photo ->
              PhotoRow(
                photo = photo,
                primaryAssetId = record.assetId,
                baseUrl = baseUrl,
                armed = photoArmedId == photo.assetId,
                enabled = !busy,
                onSelect = { goToPage(index) },
                onArm = {
                  showForm = false
                  photoArmedId = if (photoArmedId == photo.assetId) null else photo.assetId
                },
                onConfirm = {
                  photoArmedId = null
                  onDeletePhoto(photo.assetId)
                },
              )
            }
          }

          if (decisions.isNotEmpty()) {
            HorizontalDivider()
            DecisionBlock(decisions)
          }

          HorizontalDivider()

          if (canReanalyze) {
            if (showForm) {
              OutlinedTextField(
                value = notes,
                onValueChange = { notes = it },
                label = { Text("修正说明") },
                placeholder = { Text(REANALYZE_PLACEHOLDER) },
                minLines = 3,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
              )
              Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                  onClick = { onReanalyze(notes) },
                  enabled = !busy && notes.isNotBlank(),
                ) {
                  Text(if (busy) "分析中…（约半分钟）" else "提交")
                }
                TextButton(onClick = { showForm = false }, enabled = !busy) { Text("取消") }
              }
            } else {
              OutlinedButton(
                onClick = {
                  // 打开表单就解除删除武装态，避免两个危险动作叠在一起
                  mealArmed = false
                  photoArmedId = null
                  showForm = true
                },
                enabled = !busy,
              ) {
                Text("重新分析")
              }
            }
          }

          if (mealArmed) {
            Button(
              onClick = {
                mealArmed = false
                onDeleteMeal()
              },
              enabled = !busy,
            ) {
              Text("确认删除整餐？")
            }
          } else {
            OutlinedButton(
              onClick = {
                showForm = false
                mealArmed = true
              },
              enabled = !busy,
            ) {
              Text("删除整餐")
            }
          }

          if (busy) {
            Row(verticalAlignment = Alignment.CenterVertically) {
              CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
              Text("  处理中…", style = MaterialTheme.typography.labelSmall)
            }
          }

          Text(
            text = "删除后照片会进忽略列表，cron 不会再同步回来",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(bottom = 24.dp),
          )
        }
      }
    }
  }
}

/** 单张照片一行：缩略图、时间，以及形态 A/B 各自的明细。 */
@Composable
private fun PhotoRow(
  photo: PhotoDto,
  primaryAssetId: String,
  baseUrl: String,
  armed: Boolean,
  enabled: Boolean,
  onSelect: () -> Unit,
  onArm: () -> Unit,
  onConfirm: () -> Unit,
) {
  val mergedZeroRow = MealGrouping.isMergedZeroRow(photo, primaryAssetId)

  Row(
    modifier = Modifier.fillMaxWidth().clickable(onClick = onSelect).padding(vertical = 6.dp),
    horizontalArrangement = Arrangement.spacedBy(10.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    AsyncImage(
      model = ImageUrl.thumbnail(baseUrl, photo.thumbnailUrl),
      contentDescription = null,
      contentScale = ContentScale.Crop,
      modifier =
        Modifier.size(40.dp)
          .clip(RoundedCornerShape(6.dp))
          .background(MaterialTheme.colorScheme.surfaceVariant),
    )

    Column(modifier = Modifier.weight(1f)) {
      Text(
        text = "${TimeFmt.clock(photo.photoTime)}  ${photo.meal.ifBlank { "—" }}",
        style = MaterialTheme.typography.labelMedium,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
      )
      if (mergedZeroRow) {
        // 形态 A 从行：四项全 0 表示"已并入主行"，不是没吃（2026-08-29 事故的教训）
        Text(
          text = "已并入整餐估算",
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
      } else {
        if (photo.mealDetail.isNotBlank()) {
          Text(
            text = photo.mealDetail,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
          )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
          Text(
            text = "${photo.calories.roundToInt()} kcal",
            style = MaterialTheme.typography.labelSmall,
          )
          Spacer(modifier = Modifier.width(12.dp))
          MacroText(
            p = photo.proteinG,
            c = photo.carbsG,
            f = photo.fatG,
            style = MaterialTheme.typography.labelSmall,
          )
        }
      }
    }

    if (armed) {
      TextButton(onClick = onConfirm, enabled = enabled) {
        Text("确认?", color = MaterialTheme.colorScheme.error)
      }
    } else {
      TextButton(onClick = onArm, enabled = enabled) { Text("✕") }
    }
  }
}

/** 🤖 AI 决策折叠块。 */
@Composable
private fun DecisionBlock(decisions: List<DecisionDto>) {
  var expanded by remember { mutableStateOf(false) }

  Column {
    TextButton(onClick = { expanded = !expanded }) {
      Text(if (expanded) "🤖 AI 决策 ▴" else "🤖 AI 决策（${decisions.size}）▾")
    }
    if (expanded) {
      decisions.forEach { decision ->
        Column(
          modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
          verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
          Text(
            text = Decisions.headline(decision),
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
          )
          if (decision.reasoning.isNotBlank()) {
            Text(text = decision.reasoning, style = MaterialTheme.typography.bodySmall)
          }
          decision.promptForGemini?.takeIf { it.isNotBlank() }?.let { prompt ->
            Text(
              text = "给 Gemini 的提示词",
              style = MaterialTheme.typography.labelSmall,
              color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(text = prompt, style = MaterialTheme.typography.bodySmall)
          }
        }
      }
    }
  }
}

private fun photoFullUrl(baseUrl: String, photo: PhotoDto, record: RecordDto): String? =
  ImageUrl.full(
    base = baseUrl,
    thumbnailUrl = photo.thumbnailUrl,
    // 替换图只挂在主记录上，从行没有这个字段
    replacementImage = if (photo.assetId == record.assetId) record.replacementImage else "",
  )
