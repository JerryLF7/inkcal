package com.jerrylf.inkcal.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.BuildConfig
import com.jerrylf.inkcal.domain.TimeFmt
import com.jerrylf.inkcal.ui.app.AppViewModel
import kotlin.math.roundToInt

/**
 * 设置页，对应 docs/android-app-spec.md §8.7。
 *
 * 体征参数是 BMR 的输入，BMR 又是热量缺口的分母，所以保存后要立刻刷新全局缓存。
 * 「服务器」分组沿用 AppViewModel 的状态。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
  appViewModel: AppViewModel,
  settingsViewModel: SettingsViewModel = viewModel(),
) {
  val settings by settingsViewModel.state.collectAsStateWithLifecycle()
  val baseUrl by appViewModel.baseUrl.collectAsStateWithLifecycle()
  val dataSummary by appViewModel.dataSummary.collectAsStateWithLifecycle()
  val busy by appViewModel.busy.collectAsStateWithLifecycle()
  val snackbarHostState = remember { SnackbarHostState() }

  var urlInput by rememberSaveable { mutableStateOf("") }
  var showDatePicker by remember { mutableStateOf(false) }

  LaunchedEffect(baseUrl) { urlInput = baseUrl }

  LaunchedEffect(settings.message) {
    settings.message?.let {
      snackbarHostState.showSnackbar(it)
      settingsViewModel.consumeMessage()
    }
  }

  Box(modifier = Modifier.fillMaxSize()) {
    Column(
      modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
      verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
      Text("设置", style = MaterialTheme.typography.headlineMedium)

      // ── 体征参数 ──────────────────────────────────────────────
      Text("体征参数", style = MaterialTheme.typography.titleMedium)
      Text(
        "用于计算 BMR。留空则不改动该项。",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )

      OutlinedTextField(
        value = settings.height,
        onValueChange = settingsViewModel::setHeight,
        label = { Text("身高（cm）") },
        singleLine = true,
        isError = settings.validationError == null && settings.height.isNotBlank() && settings.height.toDoubleOrNull() == null,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth(),
      )
      OutlinedTextField(
        value = settings.weight,
        onValueChange = settingsViewModel::setWeight,
        label = { Text("体重（kg）") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth(),
      )

      OutlinedTextField(
        value = settings.birthdate,
        onValueChange = settingsViewModel::setBirthdate,
        label = { Text("出生日期") },
        placeholder = { Text("YYYY-MM-DD") },
        singleLine = true,
        readOnly = true,
        trailingIcon = {
          TextButton(onClick = { showDatePicker = true }) { Text("选择") }
        },
        modifier = Modifier.fillMaxWidth(),
      )

      Text("生理性别（BMR 公式用）", style = MaterialTheme.typography.labelMedium)
      SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        listOf("male" to "男", "female" to "女").forEachIndexed { index, (value, label) ->
          SegmentedButton(
            selected = settings.gender == value,
            onClick = { settingsViewModel.setGender(value) },
            shape = SegmentedButtonDefaults.itemShape(index = index, count = 2),
          ) {
            Text(label)
          }
        }
      }

      settings.validationError?.let {
        Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
      }

      Text(
        text = settings.bmr?.let { "BMR ${it.roundToInt()} kcal/天" } ?: "BMR —（体征未填齐）",
        style = MaterialTheme.typography.titleMedium,
      )

      // ── Calo 上下文窗口 ───────────────────────────────────────
      HorizontalDivider()
      Text("Calo 上下文窗口", style = MaterialTheme.typography.titleMedium)
      Text(
        "${settings.chatWindow} 轮",
        style = MaterialTheme.typography.bodyMedium,
      )
      Slider(
        value = settings.chatWindow.toFloat(),
        onValueChange = { settingsViewModel.setChatWindow(it.roundToInt()) },
        valueRange = 5f..50f,
        steps = 44,
        enabled = !settings.loading,
      )

      Button(
        onClick = settingsViewModel::save,
        enabled = !settings.saving && !settings.loading && settings.validationError == null,
        modifier = Modifier.fillMaxWidth(),
      ) {
        Text(if (settings.saving) "保存中…" else "保存")
      }

      // ── 服务器 ────────────────────────────────────────────────
      HorizontalDivider()
      Text("服务器", style = MaterialTheme.typography.titleMedium)
      Text(
        text = dataSummary?.let { summary ->
          "数据概况：${summary.records} 条记录" +
            // 服务端时间戳是 UTC，DataVersion 已转成 HKT，这里标出来免得再猜
            (summary.lastWrite?.let { " · 最后写入 $it（HKT）" } ?: " · 暂无写入")
        } ?: "数据概况：—",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )
      OutlinedTextField(
        value = urlInput,
        onValueChange = { urlInput = it },
        label = { Text("服务器地址") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        modifier = Modifier.fillMaxWidth(),
      )
      Button(
        onClick = { appViewModel.saveServer(urlInput) },
        enabled = !busy && urlInput.isNotBlank(),
        modifier = Modifier.fillMaxWidth(),
      ) {
        Text("保存并重连")
      }
      OutlinedButton(
        onClick = appViewModel::logout,
        enabled = !busy,
        modifier = Modifier.fillMaxWidth(),
      ) {
        Text("退出登录")
      }

      // ── 关于 ──────────────────────────────────────────────────
      HorizontalDivider()
      Text("关于", style = MaterialTheme.typography.titleMedium)
      Text(
        "App 版本 ${BuildConfig.VERSION_NAME}（${BuildConfig.VERSION_CODE}）",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )

      if (busy || settings.loading) {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
      }
    }

    SnackbarHost(
      hostState = snackbarHostState,
      modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
    )
  }

  if (showDatePicker) {
    val pickerState =
      rememberDatePickerState(initialSelectedDateMillis = TimeFmt.pickerMillis(settings.birthdate))
    DatePickerDialog(
      onDismissRequest = { showDatePicker = false },
      confirmButton = {
        TextButton(
          onClick = {
            pickerState.selectedDateMillis?.let {
              settingsViewModel.setBirthdate(TimeFmt.dateFromPickerMillis(it))
            }
            showDatePicker = false
          }
        ) {
          Text("确定")
        }
      },
      dismissButton = {
        TextButton(onClick = { showDatePicker = false }) { Text("取消") }
      },
    ) {
      DatePicker(state = pickerState)
    }
  }
}
