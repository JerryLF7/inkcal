package com.jerrylf.inkcal.ui.app

import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
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

  Scaffold(
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
      onBack = { backStack.removeLastOrNull() },
      modifier = Modifier.padding(inner),
      // 一级 Tab 切换走 M3 的 Top level 过渡（fade through）
      transitionSpec = { topLevelFadeThrough() },
      entryProvider =
        entryProvider {
          entry<RecordsRoute> { RecordsTab() }
          entry<CaloRoute> { CaloScreen() }
          entry<SettingsRoute> { SettingsScreen(appViewModel = viewModel) }
        },
    )
  }
}
