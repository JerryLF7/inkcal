package com.jerrylf.inkcal.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jerrylf.inkcal.ui.app.AppViewModel

/**
 * 设置页。当前只有「服务器」分组；体征参数、BMR、Calo 上下文窗口见
 * docs/android-app-spec.md §8.7，尚未实现。
 */
@Composable
fun SettingsScreen(version: String, viewModel: AppViewModel) {
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val busy by viewModel.busy.collectAsStateWithLifecycle()

  var urlInput by rememberSaveable { mutableStateOf("") }
  LaunchedEffect(baseUrl) { urlInput = baseUrl }

  Column(
    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Text("设置", style = MaterialTheme.typography.headlineMedium)

    Text("服务器", style = MaterialTheme.typography.titleMedium)
    Text(
      "数据版本 $version",
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
      onClick = { viewModel.saveServer(urlInput) },
      enabled = !busy && urlInput.isNotBlank(),
      modifier = Modifier.fillMaxWidth(),
    ) {
      Text("保存并重连")
    }
    OutlinedButton(
      onClick = { viewModel.logout() },
      enabled = !busy,
      modifier = Modifier.fillMaxWidth(),
    ) {
      Text("退出登录")
    }

    HorizontalDivider()
    Text(
      "体征参数、BMR 与 Calo 上下文窗口还没实现。",
      style = MaterialTheme.typography.bodyMedium,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
  }
}
