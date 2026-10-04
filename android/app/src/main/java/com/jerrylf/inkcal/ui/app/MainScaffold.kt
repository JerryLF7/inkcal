package com.jerrylf.inkcal.ui.app

import androidx.compose.animation.core.tween
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.IntOffset
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

/** Tab 在顺序里的下标，决定滑动方向；不是一级路由时返回 -1（不会比出方向）。 */
private fun tabIndexOf(key: Any?): Int = Tab.entries.indexOfFirst { it.route == key }

/** 一级导航骨架：底部 Tab + Nav3。设置页不参与左右滑动（滑动还没做）。 */
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
      // 一级 Tab 按顺序左右滑动（默认是渐入渐出）：往右的 Tab 从右侧滑入，反之从左侧
      transitionSpec = {
        val from = tabIndexOf(initialState.entries.lastOrNull()?.contentKey)
        val to = tabIndexOf(targetState.entries.lastOrNull()?.contentKey)
        val spec = tween<IntOffset>(280)
        if (to > from) {
          slideInHorizontally(spec) { it } togetherWith slideOutHorizontally(spec) { -it }
        } else {
          slideInHorizontally(spec) { -it } togetherWith slideOutHorizontally(spec) { it }
        }
      },
      entryProvider =
        entryProvider {
          entry<RecordsRoute> { RecordsTab() }
          entry<CaloRoute> { CaloScreen() }
          entry<SettingsRoute> { SettingsScreen(appViewModel = viewModel) }
        },
    )
  }
}
