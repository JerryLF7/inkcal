package com.jerrylf.inkcal.ui.app

import androidx.activity.BackEventCompat
import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.AospBackVisuals
import com.jerrylf.inkcal.domain.BackSwipeEdge
import com.jerrylf.inkcal.domain.PredictiveBackMath
import com.jerrylf.inkcal.ui.records.MealDetailContent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

private val MaxRoundedShape = RoundedCornerShape(PredictiveBackMath.MAX_CORNER_DP.dp)

/**
 * 详情覆盖层的数据槽：统一承接「记录页」与「Calo 聊天页」两个入口。
 *
 * 挂在 `MainScaffold` 顶层，压过底部 `NavigationBar` 并延伸到状态栏/导航栏下方（edge-to-edge），
 * 这样预测性返回缩放时底下自然露出完整的一级页与底部导航栏。
 */
data class DetailOverlaySlot(
  val owner: String,
  val record: RecordDto,
  val baseUrl: String,
  val decisions: List<DecisionDto>,
  val busy: Boolean,
  val onClose: () -> Unit,
  val onDeleteMeal: () -> Unit,
  val onDeletePhoto: (String) -> Unit,
  val onReanalyze: (String, () -> Unit) -> Unit,
)

internal enum class OverlayPhase {
  HIDDEN,
  ENTERING,
  OPEN,
  BACK_GESTURE,
  BACK_CANCELLING,
  CLOSING,
}

/**
 * AOSP 风格两阶段预测性返回状态机。
 *
 * 关键不变量：
 * 1. **快照留存**：关闭期间保留 [retainedSlot]，直到退场动画彻底结束再清空，避免 `nullable?.let` 导致的松手闪没。
 * 2. **独立协程域**：取消手势的弹回与松手提交的退场动画一律跑在外部 [scope] 上——
 *    `activity-compose` 的 `ComposePredictiveBackHandler.onBackCancelled()` 会取消自身的 `activeJob`，
 *    在 `catch (CancellationException)` 里直接挂起 `animateTo` 会立刻再次被取消而失效。
 * 3. **零重组绘制**：动画帧只在 `graphicsLayer {}` 内部读取 `Animatable.value`，拖动期间 0 次重组。
 */
@Stable
class AospDetailOverlayState(private val scope: CoroutineScope) {

  internal var phase by mutableStateOf(OverlayPhase.HIDDEN)
    private set

  internal var retainedSlot by mutableStateOf<DetailOverlaySlot?>(null)
    private set

  private var activeOwner: String? = null

  private val enterProgress = Animatable(0f)
  private val backProgress = Animatable(0f)
  private val touchDeltaY = Animatable(0f)
  private val commitProgress = Animatable(0f)

  private var swipeEdge by mutableStateOf(BackSwipeEdge.LEFT)
  private var commitSnapshot by mutableStateOf(AospBackVisuals())

  private var widthPx by mutableFloatStateOf(0f)
  private var heightPx by mutableFloatStateOf(0f)
  private var density by mutableFloatStateOf(1f)

  private var transitionJob: Job? = null

  /** 是否正在屏幕中显示（包含进退场动画中）。 */
  val isVisible: Boolean
    get() = phase != OverlayPhase.HIDDEN && retainedSlot != null

  /** 只有可交互期间才注册系统返回拦截；退场中禁掉以防二次手势打断收尾动画。 */
  val isInteractive: Boolean
    get() =
      retainedSlot != null &&
        phase != OverlayPhase.HIDDEN &&
        phase != OverlayPhase.CLOSING

  internal fun updateMetrics(width: Float, height: Float, density: Float) {
    this.widthPx = width
    this.heightPx = height
    this.density = density
  }

  /**
   * 同步业务侧详情槽位：
   * - `null → 非空`：启动 AOSP 推入动画；
   * - `非空 → 非空`（同条或原地更新，如重分析/单张移除晋升）：直接刷新内容，不重播进场动画；
   * - `非空 → null`（业务侧主动关闭，如删除整餐后清空锚点）：自动播 AOSP 退场动画再卸载。
   */
  fun syncSlot(owner: String, slot: DetailOverlaySlot?) {
    if (slot == null) {
      if (activeOwner != owner) return
      activeOwner = null
      if (retainedSlot != null && phase != OverlayPhase.CLOSING && phase != OverlayPhase.HIDDEN) {
        startExitAnimation(notifyOwnerClose = false, edge = BackSwipeEdge.LEFT)
      }
      return
    }

    // 退场动画进行中收到同一归属方的普通重组（此时 ViewModel 尚未收到 onClose），不能打断退场。
    if (phase == OverlayPhase.CLOSING && activeOwner == owner) {
      retainedSlot = slot
      return
    }

    val wasHidden = phase == OverlayPhase.HIDDEN || retainedSlot == null
    activeOwner = owner
    retainedSlot = slot
    if (wasHidden) {
      startEnterAnimation()
    }
  }

  private fun startEnterAnimation() {
    transitionJob?.cancel()
    phase = OverlayPhase.ENTERING
    transitionJob =
      scope.launch {
        backProgress.snapTo(0f)
        touchDeltaY.snapTo(0f)
        commitProgress.snapTo(0f)
        enterProgress.snapTo(0f)
        enterProgress.animateTo(
          targetValue = 1f,
          animationSpec =
            tween(
              durationMillis = PredictiveBackMath.ENTER_DURATION_MS,
              // 必须用线性时间进度：缓动曲线与透明度窗口由 PredictiveBackMath 分别计算
              easing = LinearEasing,
            ),
        )
        if (phase == OverlayPhase.ENTERING) {
          phase = OverlayPhase.OPEN
        }
      }
  }

  internal suspend fun onBackStarted(edge: BackSwipeEdge) {
    transitionJob?.cancel()
    swipeEdge = edge
    enterProgress.snapTo(1f)
    commitProgress.snapTo(0f)
    phase = OverlayPhase.BACK_GESTURE
  }

  internal suspend fun onBackProgressed(
    progress: Float,
    edge: BackSwipeEdge,
    deltaY: Float,
  ) {
    if (phase != OverlayPhase.BACK_GESTURE) {
      onBackStarted(edge)
    }
    swipeEdge = edge
    backProgress.snapTo(progress)
    touchDeltaY.snapTo(deltaY)
  }

  /** 手势取消：必须在外部 [scope] 上跑弹簧弹回，避开已取消的 PredictiveBackHandler job。 */
  internal fun onBackCancelled() {
    if (phase != OverlayPhase.BACK_GESTURE) return
    transitionJob?.cancel()
    phase = OverlayPhase.BACK_CANCELLING
    transitionJob =
      scope.launch {
        val spec =
          spring<Float>(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = Spring.StiffnessMedium,
          )
        launch { touchDeltaY.animateTo(0f, spec) }
        backProgress.animateTo(0f, spec)
        if (phase == OverlayPhase.BACK_CANCELLING) {
          phase = OverlayPhase.OPEN
        }
      }
  }

  /** 手势松手确认或点击返回箭头：冻结当前精确形变，平滑接力阶段二退场。 */
  fun requestDismiss(edge: BackSwipeEdge = swipeEdge) {
    if (phase == OverlayPhase.HIDDEN || phase == OverlayPhase.CLOSING) return
    startExitAnimation(notifyOwnerClose = true, edge = edge)
  }

  private fun startExitAnimation(notifyOwnerClose: Boolean, edge: BackSwipeEdge) {
    val closingSlot = retainedSlot ?: return
    val effectiveEdge =
      if (phase == OverlayPhase.BACK_GESTURE || phase == OverlayPhase.BACK_CANCELLING) {
        swipeEdge
      } else {
        edge
      }
    swipeEdge = effectiveEdge
    commitSnapshot = captureCommitSnapshot(effectiveEdge)

    transitionJob?.cancel()
    phase = OverlayPhase.CLOSING
    transitionJob =
      scope.launch {
        commitProgress.snapTo(0f)
        commitProgress.animateTo(
          targetValue = 1f,
          animationSpec =
            tween(
              durationMillis = PredictiveBackMath.COMMIT_DURATION_MS,
              // 必须用线性时间进度：0.28 用 StandardDecelerate 喂给 alpha 阈值导致 29ms 内闪没
              easing = LinearEasing,
            ),
        )
        backProgress.snapTo(0f)
        touchDeltaY.snapTo(0f)
        enterProgress.snapTo(0f)
        commitProgress.snapTo(0f)
        // 先通知 ViewModel 清锚点，再切回 HIDDEN，防止同一帧内因旧锚点仍在而误重开
        if (notifyOwnerClose) {
          closingSlot.onClose()
        }
        phase = OverlayPhase.HIDDEN
        retainedSlot = null
        activeOwner = null
      }
  }

  private fun captureCommitSnapshot(edge: BackSwipeEdge): AospBackVisuals =
    when (phase) {
      OverlayPhase.ENTERING -> PredictiveBackMath.enter(enterProgress.value, density)
      OverlayPhase.BACK_GESTURE,
      OverlayPhase.BACK_CANCELLING ->
        PredictiveBackMath.preCommit(
          progress = backProgress.value,
          edge = edge,
          touchDeltaY = touchDeltaY.value,
          widthPx = widthPx,
          heightPx = heightPx,
          density = density,
        )
      else ->
        PredictiveBackMath.preCommit(
          progress = 0f,
          edge = edge,
          touchDeltaY = 0f,
          widthPx = widthPx,
          heightPx = heightPx,
          density = density,
        )
    }

  /**
   * 供 `graphicsLayer {}` 在绘制阶段调用（不触发重组）。
   * 返回 `null` 表示覆盖层未打开或处于完全静止全屏态（底页可保持恒等变换）。
   */
  internal fun currentVisuals(
    layerWidthPx: Float,
    layerHeightPx: Float,
    layerDensity: Float,
  ): AospBackVisuals? =
    when (phase) {
      OverlayPhase.HIDDEN -> null
      OverlayPhase.OPEN -> null
      OverlayPhase.ENTERING -> PredictiveBackMath.enter(enterProgress.value, layerDensity)
      OverlayPhase.BACK_GESTURE,
      OverlayPhase.BACK_CANCELLING ->
        PredictiveBackMath.preCommit(
          progress = backProgress.value,
          edge = swipeEdge,
          touchDeltaY = touchDeltaY.value,
          widthPx = layerWidthPx,
          heightPx = layerHeightPx,
          density = layerDensity,
        )
      OverlayPhase.CLOSING ->
        PredictiveBackMath.postCommit(
          rawTimeProgress = commitProgress.value,
          snapshot = commitSnapshot,
          edge = swipeEdge,
          density = layerDensity,
        )
    }
}

@Composable
fun rememberAospDetailOverlayState(): AospDetailOverlayState {
  val scope = rememberCoroutineScope()
  return remember(scope) { AospDetailOverlayState(scope) }
}

/**
 * 挂在底页（`MainScaffold` 的 `Scaffold`）上的视差与缩放修饰符。
 * 全部计算都在 `graphicsLayer {}` 绘制阶段完成，0 重组。
 */
fun Modifier.aospBackBackground(state: AospDetailOverlayState): Modifier =
  this.graphicsLayer {
    val visuals = state.currentVisuals(size.width, size.height, density)
    if (visuals != null) {
      scaleX = visuals.bgScale
      scaleY = visuals.bgScale
      translationX = visuals.bgTranslationX
    }
  }

/**
 * 顶层 AOSP 预测性返回详情覆盖层。
 *
 * 位于 `MainScaffold` 根 `Box` 中、压在 `Scaffold` 之上、`SnackbarHost` 之下。
 */
@Composable
fun AospDetailOverlay(state: AospDetailOverlayState) {
  val slot = state.retainedSlot

  PredictiveBackHandler(enabled = state.isInteractive) { progressFlow ->
    var started = false
    var initialTouchY = Float.NaN
    var lastEdge = BackSwipeEdge.LEFT
    try {
      progressFlow.collect { event ->
        val edge =
          if (event.swipeEdge == BackEventCompat.EDGE_RIGHT) {
            BackSwipeEdge.RIGHT
          } else {
            BackSwipeEdge.LEFT
          }
        lastEdge = edge
        if (!started) {
          started = true
          initialTouchY = event.touchY
          state.onBackStarted(edge)
        }
        val deltaY = if (initialTouchY.isNaN()) 0f else event.touchY - initialTouchY
        state.onBackProgressed(progress = event.progress, edge = edge, deltaY = deltaY)
      }
      // 手势松手确认，或传统三键返回（未触发任何 progress 事件，started == false）
      state.requestDismiss(edge = if (started) lastEdge else BackSwipeEdge.LEFT)
    } catch (_: CancellationException) {
      state.onBackCancelled()
    }
  }

  if (!state.isVisible || slot == null) return

  Box(modifier = Modifier.fillMaxSize()) {
    // 暗化遮罩 + 触摸吸收层：彻底防止点穿到底下的列表与底部导航栏
    Box(
      modifier =
        Modifier.fillMaxSize()
          .graphicsLayer {
            val visuals = state.currentVisuals(size.width, size.height, density)
            alpha = visuals?.scrimAlpha ?: 0f
          }
          .background(Color.Black)
          .clickable(
            interactionSource = remember { MutableInteractionSource() },
            indication = null,
            onClick = {},
          )
    )

    // 前景详情页：零重组 graphicsLayer 承载缩放、双侧边距位移、纵向跟随、动态圆角与提交淡出
    Box(
      modifier =
        Modifier.fillMaxSize().graphicsLayer {
          val visuals = state.currentVisuals(size.width, size.height, density)
          if (visuals != null) {
            scaleX = visuals.fgScale
            scaleY = visuals.fgScale
            translationX = visuals.fgTranslationX
            translationY = visuals.fgTranslationY
            alpha = visuals.fgAlpha
            if (visuals.fgCornerRadiusDp > 0.5f) {
              clip = true
              shape =
                if (visuals.fgCornerRadiusDp >= PredictiveBackMath.MAX_CORNER_DP - 0.5f) {
                  MaxRoundedShape
                } else {
                  RoundedCornerShape(visuals.fgCornerRadiusDp.dp)
                }
            }
          }
        }
    ) {
      MealDetailContent(
        record = slot.record,
        baseUrl = slot.baseUrl,
        decisions = slot.decisions,
        busy = slot.busy,
        onClose = { state.requestDismiss(BackSwipeEdge.LEFT) },
        onDeleteMeal = slot.onDeleteMeal,
        onDeletePhoto = slot.onDeletePhoto,
        onReanalyze = slot.onReanalyze,
      )
    }
  }
}
