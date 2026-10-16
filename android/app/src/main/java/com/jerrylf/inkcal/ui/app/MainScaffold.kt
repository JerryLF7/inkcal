package com.jerrylf.inkcal.ui.app

import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.jerrylf.inkcal.domain.TimeFmt
import com.jerrylf.inkcal.ui.calo.CaloScreen
import com.jerrylf.inkcal.ui.records.MealDetailDialog
import com.jerrylf.inkcal.ui.records.RangeViewModel
import com.jerrylf.inkcal.ui.records.RecordsTab
import com.jerrylf.inkcal.ui.records.RecordsViewModel
import com.jerrylf.inkcal.ui.settings.SettingsScreen
import kotlinx.serialization.Serializable

@Serializable
data object RecordsRoute : NavKey

@Serializable
data object CaloRoute : NavKey

@Serializable
data object SettingsRoute : NavKey

/**
 * 餐卡详情页。
 *
 * **参数只是入栈时的凭据**：真正渲染哪条记录取的是 `RecordsViewModel.detailAnchor`——
 * 单张移除后锚点会被切到晋升的新主行，路由参数不会跟着变，但那个锚点会
 * （详情页因此永远不会渲染成一条已经不存在的记录）。
 */
@Serializable
data class MealDetailRoute(val assetId: String) : NavKey

/**
 * 三个一级 Tab。图标取自 material-icons-core（material3 不自带，见版本目录注释），
 * 只是占位级别的选择，等功能齐了再挑合适的。
 */
private enum class Tab(val route: NavKey, val label: String, val icon: ImageVector) {
  Records(RecordsRoute, "记录", Icons.Filled.DateRange),
  Calo(CaloRoute, "Calo", Icons.Filled.Face),
  Settings(SettingsRoute, "设置", Icons.Filled.Settings),
}

/** fade through 的时序：旧页 90ms 快速淡出，新页延后 90ms 再花 210ms 淡入（合计 300ms）。 */
private const val FadeOutMillis = 90
private const val FadeInMillis = 210

/** 推进/退回层级的时长（M3 medium2 = 300ms）。 */
private const val DetailMotionMillis = 300

/**
 * 一级 Tab 之间的转场：M3 的 **Top level** 过渡（fade through）——
 * "The exiting screen quickly fades out and then the entering screen fades in."
 *
 * **不要换回方向性滑动**：横向平移是 **Lateral** 的语汇，属于同级可横滑的内容；
 * 点底部导航栏切换目的地必须用 Top level 过渡（M3 Navigation bar 规范原文）。
 */
private fun topLevelFadeThrough(): ContentTransform =
  ContentTransform(
    targetContentEnter = fadeIn(tween(durationMillis = FadeInMillis, delayMillis = FadeOutMillis)),
    initialContentExit = fadeOut(tween(durationMillis = FadeOutMillis)),
  )

/**
 * 推进一层（进详情页）：M3 的 **Forward and backward**。
 * M3 原文说 Android 的做法是 "a fade as screens slide"，并且**不用滑满整屏宽**
 * （减少运动量），所以这里只滑 1/4 屏宽并配合淡入淡出。
 */
private fun forwardPush(): ContentTransform =
  (slideInHorizontally(tween(DetailMotionMillis)) { it / 4 } +
    fadeIn(tween(DetailMotionMillis))) togetherWith
    (slideOutHorizontally(tween(DetailMotionMillis)) { -it / 4 } +
      fadeOut(tween(DetailMotionMillis)))

/**
 * 退出一层（从详情返回）：[forwardPush] 的**镜像**——详情页向右滑出、底下的列表从左侧滑回。
 *
 * **不要退回 NavDisplay 的默认退场**：它默认是「整页等比缩小」
 * （2026-10-16 用户实测："只是整个页面等比缩放，和原生的返回动画完全不一样"）。
 * M3 的 Forward and backward 要求用「滑动 + 淡入淡出」，缩放是 Enter/exit 里被明确劝阻的做法
 * （Scale and z-axis motion is avoided since they imply elevation change）。
 */
private fun backwardPop(): ContentTransform =
  (slideInHorizontally(tween(DetailMotionMillis)) { -it / 4 } +
    fadeIn(tween(DetailMotionMillis))) togetherWith
    (slideOutHorizontally(tween(DetailMotionMillis)) { it / 4 } +
      fadeOut(tween(DetailMotionMillis)))

/**
 * **跟手预览**（手势进行中用的转场）：与 [backwardPop] **同形状**即可。
 *
 * 这里**千万不要**写 `tween(0)` 之类的「逐帧落位」——那是错的（2026-10-16 实测：改成 tween(0)
 * 之后返回直接变成瞬间切换、一点动画都没有）。原因：跟手的定位是 Compose 自己在转场层做的
 * （它按手势进度 seek 正在跑的转场），spec 只负责定义**转场的形状与真实时长**，时长给 0 就等于没有动画。
 * 另外，nav3 默认实现里那个 `progress` 参数其实**根本没被读取**（反编译确认：lambda 收下 Int 就丢掉，
 * 只返回 `fadeIn(spring) togetherWith scaleOut(0.7f)`）——所以别想着自己拿 progress 算偏移。
 */
@Suppress("UNUSED_PARAMETER")
private fun backwardPopPreview(progress: Int): ContentTransform = backwardPop()

/**
 * 一级导航骨架：底部 Tab + Nav3，栈里同时装着「一级目的地」和「详情页」。
 *
 * 转场判据用**栈深**，不要认「这是哪一页」：`Scene.entries` 里的 entry 被装饰器链
 * 重建过，`contentKey` 不是我们的路由对象（2026-10-04 踩坑：Tab 方向因此退化成永远
 * 同一个）。栈深变了就是推进/退回层级，没变就是 Tab 之间切换。
 */
@Composable
fun MainScaffold(appViewModel: AppViewModel) {
  // 记录页的两个 ViewModel 提到这一层：详情页是导航层级里的一页，要在这里取数据、做写操作。
  // 已拍板的副作用：它们不再随 Tab 切换重建，切回来时不会重新拉一次。
  val recordsViewModel: RecordsViewModel = viewModel()
  val rangeViewModel: RangeViewModel = viewModel()

  val backStack = rememberNavBackStack(RecordsRoute)
  val snackbarHostState = remember { SnackbarHostState() }

  val detailAnchor by recordsViewModel.detailAnchor.collectAsStateWithLifecycle()
  val baseUrl by recordsViewModel.baseUrl.collectAsStateWithLifecycle()
  val decisionsByDate by recordsViewModel.decisionsByDate.collectAsStateWithLifecycle()
  val busy by recordsViewModel.busy.collectAsStateWithLifecycle()
  val toast by recordsViewModel.toast.collectAsStateWithLifecycle()
  val dayState by recordsViewModel.state.collectAsStateWithLifecycle()
  val rangeState by rangeViewModel.state.collectAsStateWithLifecycle()

  // 详情从「当前视图」的记录里查；区间数据按周/月分槽缓存，全部拼起来查最稳：
  // 在某一页点开详情后再滑走，原来的槽位还在，详情不会被误关。
  val activeRecords = remember(dayState.groups, rangeState.chunks) {
    (dayState.groups + rangeState.chunks.values.flatMap { it.groups })
      .flatMap { it.records }
      .distinctBy { it.assetId }
  }
  val detailRecord = detailAnchor?.let { anchor -> activeRecords.firstOrNull { it.assetId == anchor } }

  // 锚点 → 导航栈：锚点是唯一真相，栈跟着它走。
  LaunchedEffect(detailAnchor, detailRecord, busy, activeRecords.size) {
    val anchor = detailAnchor
    val top = backStack.lastOrNull()
    when {
      anchor != null && detailRecord != null && top !is MealDetailRoute ->
        backStack.add(MealDetailRoute(anchor))
      // 该收起详情了：锚点被清空，或组没了（整餐被删 / 单张移除后只剩这张）。
      // busy 期间不判——单张移除会把锚点切到晋升的新主行，那一刻它还没出现在列表里。
      top is MealDetailRoute && !busy &&
        (detailAnchor == null || (detailRecord == null && activeRecords.isNotEmpty())) -> {
        recordsViewModel.closeDetail()
        backStack.removeLastOrNull()
      }
    }
  }

  // 提示统一挂在这一层。原来挂在记录页，详情一盖住就看不见，才退化成系统 Toast
  // （2026-10-04 踩坑）；现在详情是栈里的一页，Snackbar 在自己身上显示才对。
  LaunchedEffect(toast) {
    toast?.let {
      snackbarHostState.showSnackbar(it)
      recordsViewModel.consumeToast()
    }
  }

  Scaffold(
    snackbarHost = { SnackbarHost(snackbarHostState) },
    bottomBar = {
      NavigationBar {
        val current = backStack.lastOrNull()
        Tab.entries.forEach { tab ->
          NavigationBarItem(
            selected = current == tab.route,
            onClick = {
              if (current != tab.route) {
                // 一级 Tab 之间不叠栈：切走就清空，返回键不会在 Tab 间来回跳
                backStack.clear()
                backStack.add(tab.route)
              }
            },
            icon = { Icon(tab.icon, contentDescription = null) },
            label = { Text(tab.label) },
          )
        }
      }
    },
  ) { inner ->
    NavDisplay(
      backStack = backStack,
      onBack = {
        // 手势/返回键退出详情时，锚点要跟着清掉，否则会被下面的 effect 又推回来
        if (backStack.lastOrNull() is MealDetailRoute) recordsViewModel.closeDetail()
        backStack.removeLastOrNull()
      },
      modifier = Modifier.padding(inner),
      transitionSpec = {
        if (targetState.entries.size != initialState.entries.size) {
          forwardPush()
        } else {
          topLevelFadeThrough()
        }
      },
      // 退场与跟手预览：**必须显式写**——NavDisplay 默认的跟手预览是「整页缩到 70%」
      // （`scaleOut(0.7f)`，反编译确认），与「返回上一级」的语义对不上。
      // 两者必须是**同一形状 + 真实时长**，见 backwardPop / backwardPopPreview 的注释。
      popTransitionSpec = { backwardPop() },
      predictivePopTransitionSpec = { progress -> backwardPopPreview(progress) },
      entryProvider =
        entryProvider {
          entry<RecordsRoute> {
            RecordsTab(dayViewModel = recordsViewModel, rangeViewModel = rangeViewModel)
          }
          entry<CaloRoute> { CaloScreen() }
          entry<SettingsRoute> { SettingsScreen(appViewModel = appViewModel) }
          entry<MealDetailRoute> {
            // 取锚点而不是路由参数，见 MealDetailRoute 的注释
            val record = detailRecord
            if (record != null) {
              MealDetailDialog(
                record = record,
                baseUrl = baseUrl,
                decisions = decisionsByDate[TimeFmt.dateOf(record.photoTime)].orEmpty(),
                busy = busy,
                asPage = true,
                onClose = recordsViewModel::closeDetail,
                onDeleteMeal = {
                  recordsViewModel.delete(
                    record.assetId,
                    photoOnly = false,
                    onSuccess = rangeViewModel::invalidate,
                  )
                },
                onDeletePhoto = { assetId ->
                  recordsViewModel.delete(assetId, photoOnly = true, onSuccess = rangeViewModel::invalidate)
                },
                onReanalyze = { notes, done ->
                  recordsViewModel.reanalyze(
                    record.assetId,
                    notes,
                    onSuccess = {
                      rangeViewModel.invalidate()
                      // 真正更新完才让详情关表单，失败时 notes 原样留在框里
                      done()
                    },
                  )
                },
              )
            }
          }
        },
    )
  }
}
