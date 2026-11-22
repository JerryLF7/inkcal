package com.jerrylf.inkcal

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.ApiFactory
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.theme.InkcalTheme
import com.jerrylf.inkcal.ui.app.installImageLoader
import com.jerrylf.inkcal.ui.records.MealDetailContent
import com.jerrylf.inkcal.ui.records.MealDetailViewModel
import kotlinx.serialization.encodeToString

/**
 * 独立餐卡详情页 Activity。
 *
 * 刻意做成独立 Activity 且**不注册任何 `BackHandler` / `PredictiveBackHandler`**：
 * 这样系统 WindowManager Shell 会自动接管跨 Activity 预测性返回（`CrossActivityBackAnimation` /
 * 各厂商原生 ROM 返回动效），自动匹配真机物理屏幕圆角、惯性曲线、底页视差与暗化遮罩，
 * 无需在 Compose 层手写模拟动画。
 */
class MealDetailActivity : ComponentActivity() {

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)

    val initialRecord =
      intent
        .getStringExtra(EXTRA_RECORD_JSON)
        ?.let { runCatching { ApiFactory.json.decodeFromString<RecordDto>(it) }.getOrNull() }
    if (initialRecord == null) {
      finish()
      return
    }
    val initialDecisions =
      intent
        .getStringExtra(EXTRA_DECISIONS_JSON)
        ?.let {
          runCatching { ApiFactory.json.decodeFromString<List<DecisionDto>>(it) }.getOrNull()
        }
        .orEmpty()

    enableEdgeToEdge()
    installImageLoader(this)

    setContent {
      InkcalTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
          val vm: MealDetailViewModel = viewModel()
          LaunchedEffect(Unit) { vm.init(initialRecord, initialDecisions) }

          val record by vm.record.collectAsStateWithLifecycle()
          val baseUrl by vm.baseUrl.collectAsStateWithLifecycle()
          val decisions by vm.decisions.collectAsStateWithLifecycle()
          val busy by vm.busy.collectAsStateWithLifecycle()
          val toast by vm.toast.collectAsStateWithLifecycle()
          val shouldFinish by vm.shouldFinish.collectAsStateWithLifecycle()

          val snackbarHostState = remember { SnackbarHostState() }

          LaunchedEffect(toast) {
            toast?.let {
              snackbarHostState.showSnackbar(it)
              vm.consumeToast()
            }
          }

          LaunchedEffect(shouldFinish) {
            if (shouldFinish) finish()
          }

          Scaffold(
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            snackbarHost = {
              SnackbarHost(
                hostState = snackbarHostState,
                modifier = Modifier.navigationBarsPadding().imePadding(),
              )
            },
          ) { _ ->
            record?.let { current ->
              MealDetailContent(
                record = current,
                baseUrl = baseUrl,
                decisions = decisions,
                busy = busy,
                onClose = { finish() },
                onDeleteMeal = vm::deleteMeal,
                onDeletePhoto = vm::deletePhoto,
                onReanalyze = vm::reanalyze,
              )
            }
          }
        }
      }
    }
  }

  companion object {
    private const val EXTRA_RECORD_JSON = "record_json"
    private const val EXTRA_DECISIONS_JSON = "decisions_json"

    fun newIntent(
      context: Context,
      record: RecordDto,
      decisions: List<DecisionDto> = emptyList(),
    ): Intent =
      Intent(context, MealDetailActivity::class.java).apply {
        putExtra(EXTRA_RECORD_JSON, ApiFactory.json.encodeToString(record))
        if (decisions.isNotEmpty()) {
          putExtra(EXTRA_DECISIONS_JSON, ApiFactory.json.encodeToString(decisions))
        }
      }
  }
}
