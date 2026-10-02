package com.jerrylf.inkcal.ui.settings

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.SettingsUpdateRequest
import com.jerrylf.inkcal.domain.BodyMetrics
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
  val loading: Boolean = true,
  val height: String = "",
  val weight: String = "",
  val birthdate: String = "",
  val gender: String = "male",
  val chatWindow: Int = 20,
  /** 服务端算的 BMR；null 表示体征没填齐。 */
  val bmr: Double? = null,
  val saving: Boolean = false,
  val message: String? = null,
) {
  val validationError: String?
    get() = BodyMetrics.firstError(height, weight, birthdate)
}

/**
 * 设置页，对应 docs/android-app-spec.md §8.7（体征 + BMR + Calo 窗口）。
 *
 * PUT 只发当前填了的键：服务端只更新出现的键，留空即「不动这一项」。
 * 保存成功后用响应里的 bmr 刷新全局缓存，日/周/月视图的缺口会立刻跟着变。
 */
class SettingsViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository

  private val _state = MutableStateFlow(SettingsUiState())
  val state: StateFlow<SettingsUiState> = _state.asStateFlow()

  init {
    load()
  }

  fun load() {
    viewModelScope.launch {
      _state.update { it.copy(loading = true) }
      runCatching { repo.settings() }
        .onSuccess { s ->
          _state.update {
            it.copy(
              loading = false,
              height = s.userHeight,
              weight = s.userWeight,
              birthdate = s.userBirthdate,
              gender = s.userGender.ifBlank { "male" },
              chatWindow = s.chatWindow,
              bmr = s.bmr,
            )
          }
        }
        .onFailure { e ->
          _state.update { it.copy(loading = false, message = "读取设置失败：${e.message}") }
        }
    }
  }

  fun setHeight(value: String) = _state.update { it.copy(height = value) }

  fun setWeight(value: String) = _state.update { it.copy(weight = value) }

  fun setBirthdate(value: String) = _state.update { it.copy(birthdate = value) }

  fun setGender(value: String) = _state.update { it.copy(gender = value) }

  fun setChatWindow(value: Int) = _state.update { it.copy(chatWindow = value.coerceIn(5, 50)) }

  fun consumeMessage() = _state.update { it.copy(message = null) }

  fun save() {
    val current = _state.value
    if (current.saving || current.validationError != null) return

    viewModelScope.launch {
      _state.update { it.copy(saving = true) }
      runCatching {
        repo.updateSettings(
          SettingsUpdateRequest(
            chatWindow = current.chatWindow,
            userHeight = current.height.trim().ifBlank { null },
            userWeight = current.weight.trim().ifBlank { null },
            userBirthdate = current.birthdate.trim().ifBlank { null },
            userGender = current.gender,
          )
        )
      }
        .onSuccess { updated ->
          // 刷新全局 BMR 缓存，日视图的缺口 chip 会立即重算
          container.bmrCache.set(updated.bmr)
          _state.update {
            it.copy(
              saving = false,
              bmr = updated.bmr,
              height = updated.userHeight,
              weight = updated.userWeight,
              birthdate = updated.userBirthdate,
              chatWindow = updated.chatWindow,
              message = "设置已保存",
            )
          }
        }
        .onFailure { e ->
          _state.update { it.copy(saving = false, message = "保存失败：${e.message}") }
        }
    }
  }
}
