package com.jerrylf.inkcal.domain

import kotlin.math.abs
import kotlin.math.sign

/** 预测性返回手势的起始边缘，与 `BackEventCompat.EDGE_LEFT` / `EDGE_RIGHT` 对应。 */
enum class BackSwipeEdge {
  LEFT,
  RIGHT,
}

/**
 * AOSP 风格预测性返回（`CrossActivityBackAnimation`）的单帧视觉状态。
 *
 * 所有位移单位均为像素（px），圆角为 dp；前景色阶、缩放、位移与底页视差、遮罩统一由本结构输出，
 * 供 `graphicsLayer` 在绘制阶段零重组读取。
 */
data class AospBackVisuals(
  val fgScale: Float = 1f,
  val fgTranslationX: Float = 0f,
  val fgTranslationY: Float = 0f,
  val fgAlpha: Float = 1f,
  val fgCornerRadiusDp: Float = 0f,
  val bgScale: Float = 1f,
  val bgTranslationX: Float = 0f,
  val scrimAlpha: Float = 0f,
)

/**
 * AOSP `CrossActivityBackAnimation`（Android 14–16 WM Shell）的两阶段纯几何计算。
 *
 * 严格区分两个阶段，不再混进单条时间轴：
 * 1. **跟手预览期（Pre-commit）**：前景保持完全不透明（`fgAlpha = 1f`），缩放 1.00 → 0.90，
 *    朝手势方向轻位移直至对侧留出 8dp 边距，同时带阻尼跟随纵向 `touchDeltaY`，裁出 28dp 圆角；
 *    底页带轻微视差与暗化遮罩露出。
 * 2. **松手提交期（Post-commit）**：从松手瞬间的精确快照接力，沿同一 `edge` 方向再滑出 48dp
 *    并在前 45% 时长内快速淡出；底页平滑归位至 `scale = 1f / translationX = 0f`，遮罩淡至 0。
 */
object PredictiveBackMath {

  const val ENTER_DURATION_MS = 300
  const val COMMIT_DURATION_MS = 280

  const val MIN_FG_SCALE = 0.90f
  const val COMMIT_END_FG_SCALE = 0.88f
  const val OPPOSITE_MARGIN_DP = 8f
  const val MAX_VERTICAL_SHIFT_DP = 36f
  const val COMMIT_EXTRA_SHIFT_DP = 48f
  const val ENTER_SHIFT_DP = 48f
  const val BG_PARALLAX_SHIFT_DP = 28f
  const val BG_MIN_SCALE = 0.97f
  const val MAX_CORNER_DP = 28f
  const val MAX_SCRIM_ALPHA = 0.36f
  const val ENTER_FADE_END = 0.35f
  const val COMMIT_FADE_END = 0.45f
  const val CORNER_RAMP_END = 0.25f

  /** 推进进入（点击卡片进详情）：前景从右侧 48dp 轻滑并快速淡入，底页轻微后退。 */
  fun enter(progress: Float, density: Float): AospBackVisuals {
    val t = progress.coerceIn(0f, 1f)
    return AospBackVisuals(
      fgScale = lerp(0.96f, 1f, t),
      fgTranslationX = (1f - t) * ENTER_SHIFT_DP * density,
      fgTranslationY = 0f,
      fgAlpha = (t / ENTER_FADE_END).coerceIn(0f, 1f),
      fgCornerRadiusDp = 0f,
      bgScale = lerp(1f, BG_MIN_SCALE, t),
      bgTranslationX = -t * BG_PARALLAX_SHIFT_DP * density,
      scrimAlpha = MAX_SCRIM_ALPHA * t,
    )
  }

  /**
   * 阶段一：跟手预览（Pre-commit）。
   *
   * - `progress == 0f` 时返回标准静息态（前景全屏无裁切；底页处于待揭示的初始视差位，此时被前景完全遮挡）。
   * - 任意 `progress ∈ [0, 1]` 期间前景始终 `fgAlpha == 1f`，绝不提前淡出。
   */
  fun preCommit(
    progress: Float,
    edge: BackSwipeEdge,
    touchDeltaY: Float,
    widthPx: Float,
    heightPx: Float,
    density: Float,
  ): AospBackVisuals {
    val p = progress.coerceIn(0f, 1f)
    val dir = directionFor(edge)

    val fgScale = lerp(1f, MIN_FG_SCALE, p)

    // 居中缩到 0.90 时左右各缩进 width * 0.05；再向对侧移至距屏边 8dp（AOSP 边距模型）。
    val halfShrinkX = widthPx * ((1f - MIN_FG_SCALE) / 2f)
    val maxShiftX = (halfShrinkX - OPPOSITE_MARGIN_DP * density).coerceAtLeast(8f * density)
    val fgTranslationX = dir * maxShiftX * p

    // 纵向随手指偏移加阻尼（quad decelerate），并限制在边距与 36dp 以内，防卡片撞顶/底。
    val halfShrinkY = heightPx * ((1f - MIN_FG_SCALE) / 2f)
    val maxShiftY =
      (halfShrinkY - OPPOSITE_MARGIN_DP * density).coerceIn(0f, MAX_VERTICAL_SHIFT_DP * density)
    val rawY = if (heightPx > 0f) (touchDeltaY / (heightPx * 0.5f)).coerceIn(-1f, 1f) else 0f
    val dampedY = sign(rawY) * (1f - (1f - abs(rawY)) * (1f - abs(rawY)))
    val fgTranslationY = maxShiftY * dampedY * p

    val fgCornerRadiusDp =
      if (p <= 0f) 0f else MAX_CORNER_DP * (p / CORNER_RAMP_END).coerceIn(0f, 1f)

    // 底页从手势起始侧轻微偏出，随拖动先归位 35%，剩余 65% 留给松手提交期丝滑减速到位。
    val bgStartX = -dir * BG_PARALLAX_SHIFT_DP * density
    val bgTranslationX = bgStartX * (1f - 0.35f * p)
    val bgScale = lerp(BG_MIN_SCALE, 0.985f, p)
    val scrimAlpha = MAX_SCRIM_ALPHA * (1f - 0.45f * p)

    return AospBackVisuals(
      fgScale = fgScale,
      fgTranslationX = fgTranslationX,
      fgTranslationY = fgTranslationY,
      fgAlpha = 1f,
      fgCornerRadiusDp = fgCornerRadiusDp,
      bgScale = bgScale,
      bgTranslationX = bgTranslationX,
      scrimAlpha = scrimAlpha,
    )
  }

  /**
   * 阶段二：松手提交退场（Post-commit）。
   *
   * 从松手瞬间冻结的 [snapshot] 无缝接力：前景继续朝同一 [edge] 方向滑出 48dp 并快速淡出，
   * 底页平滑滑回原点且缩放归 1，遮罩淡至 0。点击返回按钮或外部关闭时，以 `progress = 0` 的快照进入此阶段。
   */
  fun postCommit(
    commitProgress: Float,
    snapshot: AospBackVisuals,
    edge: BackSwipeEdge,
    density: Float,
  ): AospBackVisuals {
    val t = commitProgress.coerceIn(0f, 1f)
    val dir = directionFor(edge)
    val endScale = minOf(snapshot.fgScale, COMMIT_END_FG_SCALE)
    val fgAlpha = snapshot.fgAlpha * (1f - t / COMMIT_FADE_END).coerceIn(0f, 1f)
    val fgCornerRadiusDp =
      if (snapshot.fgCornerRadiusDp > 0f) {
        lerp(snapshot.fgCornerRadiusDp, MAX_CORNER_DP, (t * 2f).coerceIn(0f, 1f))
      } else {
        MAX_CORNER_DP * (t * 2f).coerceIn(0f, 1f)
      }

    return AospBackVisuals(
      fgScale = lerp(snapshot.fgScale, endScale, t),
      fgTranslationX = snapshot.fgTranslationX + dir * COMMIT_EXTRA_SHIFT_DP * density * t,
      fgTranslationY = snapshot.fgTranslationY,
      fgAlpha = fgAlpha,
      fgCornerRadiusDp = fgCornerRadiusDp,
      bgScale = lerp(snapshot.bgScale, 1f, t),
      bgTranslationX = lerp(snapshot.bgTranslationX, 0f, t),
      scrimAlpha = lerp(snapshot.scrimAlpha, 0f, t),
    )
  }

  private fun directionFor(edge: BackSwipeEdge): Float =
    if (edge == BackSwipeEdge.LEFT) 1f else -1f

  private fun lerp(start: Float, stop: Float, fraction: Float): Float =
    start + (stop - start) * fraction
}
