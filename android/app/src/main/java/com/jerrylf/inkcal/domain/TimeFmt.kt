package com.jerrylf.inkcal.domain

import java.time.LocalDate
import java.time.ZoneId

/**
 * photo_time 是照片拍摄地当地日历日的时间串（形如 `2026-09-30T12:34:56+08:00`）。
 *
 * 铁律（AGENTS.md §1）：一条记录属于哪天 = 字符串前 10 位。**绝不**把 photo_time 解析成
 * Instant 再按系统时区取日期——那会让拍摄地凌晨的照片日期倒退一天，进而和 cron 的
 * 幂等键对不上。所以这里一律字符串切片；只有「今天是几号」和「日期加减」才用
 * java.time，且只处理不含时间的纯日期。
 */
object TimeFmt {

  private val HKT: ZoneId = ZoneId.of("Asia/Hong_Kong")
  private val WEEKDAYS = listOf("周一", "周二", "周三", "周四", "周五", "周六", "周日")
  private val ZONE_SUFFIX = Regex("""([+-]\d{2}:\d{2})$""")

  /** 「今天」按东八区算，不跟手机本地时区走。 */
  fun hktToday(): String = LocalDate.now(HKT).toString()

  fun dateOf(photoTime: String): String = photoTime.take(10)

  /** 「12:34」 */
  fun clock(photoTime: String): String =
    if (photoTime.length >= 16) photoTime.substring(11, 16) else ""

  /**
   * 「2026-08-27 12:34 +08:00」——分钟精度，时区从末尾单独取。
   *
   * 与网页版 `fmtPhotoTimeDetail` 一致：不能直接 substring(16)，那会把秒也带进来
   * （下标 16 是秒前的冒号），拼出 `12:34 :56+08:00`。
   */
  fun detailTime(photoTime: String): String {
    if (photoTime.length < 16) return photoTime
    val head = photoTime.substring(0, 16).replace('T', ' ')
    val zone = ZONE_SUFFIX.find(photoTime)?.value
    return if (zone != null) "$head $zone" else head
  }

  /** 「周三」 */
  fun weekday(date: String): String =
    runCatching { WEEKDAYS[LocalDate.parse(date).dayOfWeek.value - 1] }.getOrDefault("")

  /** 「8月27日」 */
  fun shortDate(date: String): String =
    runCatching {
      val d = LocalDate.parse(date)
      "${d.monthValue}月${d.dayOfMonth}日"
    }.getOrDefault(date)

  /** 「2026年08月27日」 */
  fun longDate(date: String): String =
    runCatching {
      val d = LocalDate.parse(date)
      "%d年%02d月%02d日".format(d.year, d.monthValue, d.dayOfMonth)
    }.getOrDefault(date)

  /** 日期往前推 n 天。 */
  fun minusDays(date: String, days: Long): String =
    runCatching { LocalDate.parse(date).minusDays(days).toString() }.getOrDefault(date)
}
