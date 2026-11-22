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
 * 严格区分两个阶段，并且**进退场动画一律输入线性时间进度 `rawTimeProgress ∈ [0, 1]`**，
 * 在内部把「位移/缩放的缓动」和「透明度的淡出窗口」分开计算：
 * - **绝不可**把已经过 `CubicBezierEasing(0, 0, 0, 1)` 缓动的进度再除以 `0.45` 算 alpha——
 *   该曲线在 `t=0` 处斜率为无穷大，前 32ms 就冲过 0.48，导致松手 2 帧内直接闪没（0.28 踩过）。
 *
 * 两阶段模型：
 * 1. **跟手预览期（Pre-commit）**：前景保持完全不透明（`fgAlpha = 1f`），缩放 1.00 → 0.90，
 *    朝手势方向轻位移直至对侧留出 8dp 边距，同时带阻尼跟随纵向 `touchDeltaY`，裁出 28dp 圆角；
 *    底页带轻微视差与暗化遮罩露出。
 * 2. **松手提交期（Post-commit）**：从松手瞬间的精确快照接力，沿同一 `edge` 方向平滑再滑出 96dp
 *    并略微继续缩小；前景在前 12% 线性时间保持不透明以看清离手运动，随后在 12%–72% 线性时间
 *    内平滑淡出；底页同步平滑归位至 `scale = 1f / translationX = 0f`，遮罩淡至 0。
 */
object PredictiveBackMath {

  const val ENTER_DURATION_MS = 300
  const val COMMIT_DURATION_MS = 320

  const val MIN_FG_SCALE = 0.90f
  const val COMMIT_END_FG_SCALE = 0.84f
  const val OPPOSITE_MARGIN_DP = 8f
  const val MAX_VERTICAL_SHIFT_DP = 36f
  const val COMMIT_EXTRA_SHIFT_DP = 96f
  const val ENTER_SHIFT_DP = 56f
  const val BG_PARALLAX_SHIFT_DP = 28f
  const val BG_MIN_SCALE = 0.97f
  const val MAX_CORNER_DP = 28f
  const val MAX_SCRIM_ALPHA = 0.36f

  /** 进场淡入在 0%–45% 线性时间内完成（约 135ms）。 */
  const val ENTER_FADE_END = 0.45f

  /** 提交退场淡出窗口：12%–72% 线性时间（320ms 中约 38ms→230ms，避开离手瞬间闪没）。 */
  const val COMMIT_FADE_START = 0.12f
  const val COMMIT_FADE_END = 0.72f
  const val CORNER_RAMP_END = 0.25f

  /**
   * 推进进入（点击卡片进详情）。
   * [rawTimeProgress] 必须为线性时间进度 `0f..1f`（由 `LinearEasing` 驱动）。
   */
  fun enter(rawTimeProgress: Float, density: Float): AospBackVisuals {
    val raw = rawTimeProgress.coerceIn(0f, 1f)
    val motion = easeOutCubic(raw)
    val fgAlpha = smoothstep(raw / ENTER_FADE_END)
    return AospBackVisuals(
      fgScale = lerp(0.95f, 1f, motion),
      fgTranslationX = (1f - motion) * ENTER_SHIFT_DP * density,
      fgTranslationY = 0f,
      fgAlpha = fgAlpha,
      fgCornerRadiusDp = 0f,
      bgScale = lerp(1f, BG_MIN_SCALE, motion),
      bgTranslationX = -motion * BG_PARALLAX_SHIFT_DP * density,
      scrimAlpha = MAX_SCRIM_ALPHA * motion,
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
   * [rawTimeProgress] 必须为**线性**时间进度 `0f..1f`（由 `LinearEasing` 驱动）：
   * - 位移、缩放与底页归位走 `easeOutCubic(raw)`（有限初速，不瞬移）；
   * - 前景淡出走独立线性时间窗口 `[COMMIT_FADE_START, COMMIT_FADE_END]`，保证离手后能清楚看见
   *   卡片顺着滑动方向滑出并柔和消隐，而不是 2 帧内闪没。
   */
  fun postCommit(
    rawTimeProgress: Float,
    snapshot: AospBackVisuals,
    edge: BackSwipeEdge,
    density: Float,
  ): AospBackVisuals {
    val raw = rawTimeProgress.coerceIn(0f, 1f)
    val motion = easeOutCubic(raw)
    val dir = directionFor(edge)
    val endScale = minOf(snapshot.fgScale, COMMIT_END_FG_SCALE)

    val fadeFraction = (raw - COMMIT_FADE_START) / (COMMIT_FADE_END - COMMIT_FADE_START)
    val fgAlpha = snapshot.fgAlpha * (1f - smoothstep(fadeFraction))

    val fgCornerRadiusDp =
      lerp(snapshot.fgCornerRadiusDp, MAX_CORNER_DP, (raw * 3f).coerceIn(0f, 1f))

    return AospBackVisuals(
      fgScale = lerp(snapshot.fgScale, endScale, motion),
      fgTranslationX = snapshot.fgTranslationX + dir * COMMIT_EXTRA_SHIFT_DP * density * motion,
      fgTranslationY = snapshot.fgTranslationY,
      fgAlpha = fgAlpha,
      fgCornerRadiusDp = fgCornerRadiusDp,
      bgScale = lerp(snapshot.bgScale, 1f, motion),
      bgTranslationX = lerp(snapshot.bgTranslationX, 0f, motion),
      scrimAlpha = lerp(snapshot.scrimAlpha, 0f, motion),
    )
  }

  private fun directionFor(edge: BackSwipeEdge): Float =
    if (edge == BackSwipeEdge.LEFT) 1f else -1f

  private fun easeOutCubic(x: Float): Float {
    val inv = 1f - x.coerceIn(0f, 1f)
    return 1f - inv * inv * inv
  }

  private fun smoothstep(x: Float): Float {
    val c = x.coerceIn(0f, 1f)
    return c * c * (3f - 2f * c)
  }

  private fun lerp(start: Float, stop: Float, fraction: Float): Float =
    start + (stop - start) * fraction
}
