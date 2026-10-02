package com.jerrylf.inkcal.domain

import java.time.DayOfWeek
import java.time.LocalDate

/**
 * 周与月的日期算术（docs/android-app-spec.md §8.2 / §8.3）。
 *
 * 只处理不含时间的纯日期，所以用 java.time 是安全的——§4 那条铁律禁止的是把
 * `photo_time` 解析成 Instant 再按系统时区取日期，这里不涉及。
 *
 * 周一是一周起点，与网页版一致。
 */
object Periods {

  /** 该日期所在周的周一。 */
  fun mondayOf(date: String): String =
    runCatching { LocalDate.parse(date).with(DayOfWeek.MONDAY).toString() }.getOrDefault(date)

  /** 周一 + 6 天。 */
  fun weekEnd(monday: String): String = TimeFmt.plusDays(monday, 6)

  /** 往前/往后挪整周，返回新一周的周一。 */
  fun addWeeks(monday: String, delta: Long): String =
    runCatching { LocalDate.parse(monday).plusWeeks(delta).toString() }.getOrDefault(monday)

  /** 「09.29 – 10.05」 */
  fun weekLabel(monday: String): String =
    runCatching {
      val start = LocalDate.parse(monday)
      val end = start.plusDays(6)
      "%02d.%02d – %02d.%02d"
        .format(start.monthValue, start.dayOfMonth, end.monthValue, end.dayOfMonth)
    }.getOrDefault(monday)

  /** 该日期所在月的 1 号。 */
  fun monthStart(date: String): String =
    runCatching { LocalDate.parse(date).withDayOfMonth(1).toString() }.getOrDefault(date)

  /** 该日期所在月的最后一天。 */
  fun monthEnd(date: String): String =
    runCatching {
        val first = LocalDate.parse(date).withDayOfMonth(1)
        first.withDayOfMonth(first.lengthOfMonth()).toString()
      }
      .getOrDefault(date)

  /** 挪整月，返回目标月的 1 号。 */
  fun addMonths(anchor: String, delta: Long): String =
    runCatching {
        LocalDate.parse(anchor).withDayOfMonth(1).plusMonths(delta).toString()
      }
      .getOrDefault(anchor)

  /** 「2026年9月」 */
  fun monthLabel(anchor: String): String =
    runCatching {
      val d = LocalDate.parse(anchor).withDayOfMonth(1)
      "${d.year}年${d.monthValue}月"
    }.getOrDefault(anchor)

  /** 该月每一天（YYYY-MM-DD，升序）。 */
  fun daysOfMonth(anchor: String): List<String> =
    runCatching {
        val first = LocalDate.parse(anchor).withDayOfMonth(1)
        (0 until first.lengthOfMonth()).map { first.plusDays(it.toLong()).toString() }
      }
      .getOrDefault(emptyList())

  /** 该月 1 号前面要空几格（周一起始）。 */
  fun leadingBlanks(anchor: String): Int =
    runCatching { LocalDate.parse(anchor).withDayOfMonth(1).dayOfWeek.value - 1 }.getOrDefault(0)

  /** 今天所在的月？ */
  fun isCurrentMonth(anchor: String, today: String): Boolean = monthStart(anchor) == monthStart(today)

  /** 今天所在的周？ */
  fun isCurrentWeek(monday: String, today: String): Boolean = monday == mondayOf(today)

  /** 是否已经在未来（用于禁用「下一周/下一月」）。 */
  fun isFuture(mondayOrMonthStart: String, today: String): Boolean =
    mondayOrMonthStart > today
}
