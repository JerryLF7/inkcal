package com.jerrylf.inkcal.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 跨 Tab 的「数据变了」信号。
 *
 * 目前只有一处用途：Calo 里补记/改/删成功后，记录页要重拉。两个 Tab 的 ViewModel
 * 互不可见（各自 viewModel()），所以用一个共享计数器当广播——比把记录页的
 * ViewModel 提到 Activity 级、再往 Calo 传回调要轻。
 *
 * 只做递增，不携带内容：订阅方收到就自己重拉（pull 而不是 push 数据）。
 */
class DataChangeSignal {

  private val _tick = MutableStateFlow(0)
  val tick: StateFlow<Int> = _tick.asStateFlow()

  fun bump() {
    _tick.value += 1
  }
}
