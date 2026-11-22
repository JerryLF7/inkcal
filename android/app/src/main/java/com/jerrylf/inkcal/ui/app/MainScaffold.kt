package com.jerrylf.inkcal.ui.app

import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.jerrylf.inkcal.ui.calo.CaloScreen
import com.jerrylf.inkcal.ui.records.RecordsTab
import com.jerrylf.inkcal.ui.settings.SettingsScreen
import kotlinx.serialization.Serializable

@Serializable
data object RecordsRoute : NavKey

@Serializable
data object CaloRoute : NavKey

@Serializable
data object SettingsRoute : NavKey

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
 * 一级导航骨架：底部 Tab + Nav3。
 *
 * **以后往这个栈里推进层级时**（例如详情页变成真正的路由），转场判据**不要**去认「这是哪一页」：
 * `Scene.entries` 里的 entry 被装饰器链重建过，`contentKey` 不是我们的路由对象
 * （2026-10-04 踩坑：Tab 方向因此退化成永远同一个）。用**栈深**区分就够了——
 * 1→1 是 Tab 切换（Top level 过渡），+1 是推进一层，−1 是后退。
 */
@Composable
fun MainScaffold(viewModel: AppViewModel) {
  val backStack = rememberNavBackStack(RecordsRoute)
  val snackbarHostState = remember { SnackbarHostState() }
  val detailOverlay = rememberAospDetailOverlayState()
  val density = LocalDensity.current
  var bottomBarHeightPx by remember { mutableIntStateOf(0) }

  Box(
    modifier =
      Modifier.fillMaxSize().onSizeChanged { size ->
        detailOverlay.updateMetrics(
          width = size.width.toFloat(),
          height = size.height.toFloat(),
          density = density.density,
        )
      }
  ) {
    Scaffold(
      modifier = Modifier.fillMaxSize().aospBackBackground(detailOverlay),
      bottomBar = {
        NavigationBar(
          modifier = Modifier.onSizeChanged { bottomBarHeightPx = it.height },
        ) {
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
        onBack = { backStack.removeLastOrNull() },
        modifier = Modifier.padding(inner),
        // 一级 Tab 切换走 M3 的 Top level 过渡（fade through）
        transitionSpec = { topLevelFadeThrough() },
        entryProvider =
          entryProvider {
            entry<RecordsRoute> {
              RecordsTab(
                snackbarHostState = snackbarHostState,
                onDetailSlotChanged = detailOverlay::syncSlot,
              )
            }
            entry<CaloRoute> {
              CaloScreen(
                snackbarHostState = snackbarHostState,
                onDetailSlotChanged = detailOverlay::syncSlot,
              )
            }
            entry<SettingsRoute> { SettingsScreen(appViewModel = viewModel) }
          },
      )
    }

    // 详情页覆盖层：位于 Scaffold 之上，盖过底部导航栏，支持 AOSP 两阶段预测性返回
    AospDetailOverlay(state = detailOverlay)

    // 全局 Snackbar：始终压在 Scaffold 与详情页之上，避免被覆盖层挡住
    val snackbarBottomPad =
      if (detailOverlay.isVisible) {
        0.dp
      } else {
        with(density) { bottomBarHeightPx.toDp() }
      }
    SnackbarHost(
      hostState = snackbarHostState,
      modifier =
        Modifier.align(Alignment.BottomCenter)
          .imePadding()
          .then(
            if (detailOverlay.isVisible) {
              Modifier.navigationBarsPadding()
            } else {
              Modifier.padding(bottom = snackbarBottomPad)
            }
          ),
    )
  }
}
