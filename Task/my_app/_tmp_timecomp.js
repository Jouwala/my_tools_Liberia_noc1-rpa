define(["base/scripts/i18n"], function (i18n) {

    var granularityInformation;
    var rdkTimeControlGranularityItems;
    var rdkTimeRecentlyGranularityItems;
    var TIME_CODE_LIST;

    /**
     * 时间模块构造函数
     * @param {{"15min": "", "hour": "", "day": "", "week": "", "month": ""}} queryRang 默认各个粒度查询范围
     * @param {string[]} timeTypeList 时间类型集合
     */
    function timeComponentConstructor(queryRang, timeTypeList) {
        TIME_CODE_LIST = timeTypeList
        granularityInformation = [
            {key: "5min", label: i18n.report_5min, gap: queryRang["15min"]},
            {key: "15min", label: i18n.report_15min, gap: queryRang["15min"]},
            {key: "hour", label: i18n.report_hour, gap: queryRang.hour},
            {key: "day", label: i18n.report_day, gap: queryRang.day},
            {key: "week", label: i18n.report_week, gap: queryRang.week},
            {key: "month", label: i18n.report_month, gap: queryRang.month}
        ]
        rdkTimeControlGranularityItems = [
            {value: "quarter", label: i18n.report_15min, gap: _rdkTimeGapAdapter(queryRang["15min"])},
            {value: "hour", label: i18n.report_hour, gap: _rdkTimeGapAdapter(queryRang.hour)},
            {value: "date", label: i18n.report_day, gap: _rdkTimeGapAdapter(queryRang.day)},
            {value: "week", label: i18n.report_week, gap: queryRang.week},
            {value: "month", label: i18n.report_month, gap: queryRang.month}]
        rdkTimeRecentlyGranularityItems = [
            {value: "quarter", label: i18n.report_15min, gap: queryRang["15min"]},
            {value: "hour", label: i18n.report_hour, gap: queryRang.hour},
            {value: "date", label: i18n.report_day, gap: queryRang.day},
            {value: "week", label: i18n.report_week, gap: queryRang.week},
            {value: "month", label: i18n.report_month, gap: queryRang.month}]
    }

    /**
     * 获取报表下钻时间区间
     * 注意：报表查询时间语句是between..and.. 属于闭区间，下钻语句是>= ... and < ... 左闭右开区间
     * 若当前行有时间数据：
     *              若时间为多时段: 拼接hh作为startTime，并增加一个粒度作为end
     *              若时间不是标准YYYY-MM-DD格式(如ww周)：取真实数据做startTime，并增加一个粒度作为end
     *              默认当前行的clttime作为startTime，并增加一个粒度作为end
     * 若当前行没有时间数据
     *              若当前粒度是15分钟/小时粒度且非多时段查询：取上一次查询的startTime做startTime，上一次的endTime增加一个粒度作为end
     *              若是多时段查询，则默认上一次查询的startTime做startTime，上一次查询的endTime作为endTime
     *              若粒度是天，月：start和end时间相同也可以查询数据
     *              周粒度不存在相同时间场景，控件默认取第一天和最后一天
     *              默认上一次查询的startTime做startTime，上一次查询的endTime作为endTime
     * @param headers {String[]} 表头字段
     * @param currentLineShow {[String|Number]} 行显示数据
     * @param granularity {String} 时间粒度
     * @param currentLineReal {String[]} 行真实数据
     * @param lastTimeCondition {{beginTime: String,endTime: String}} 上一次查询时间条件
     * @param isMultiPeriod {Boolean} 是否勾选了多时段
     * @param isAppendGran {Boolean} 是否追加一个时间粒度，以解决前闭后开问题，xdr不需要
     * @return {String[]}
     */
    function getReportDrillTimeCondition(headers, currentLineShow, granularity, currentLineReal, lastTimeCondition, isMultiPeriod, isAppendGran) {
        var timeDimCodeIndex = TIME_CODE_LIST.findIndex(value => headers.indexOf(value) > -1)
        var startTime, endTime
        if (timeDimCodeIndex > -1) {
            var timeDimCode = TIME_CODE_LIST[timeDimCodeIndex]
            startTime = currentLineShow[timeDimCode]
            var existHHField = headers.indexOf("hh") > -1 && isMultiPeriod
            if (existHHField) {
                startTime = currentLineShow[timeDimCode] + ' ' + currentLineShow['hh'].padLeft(2, "0") + ':00:00';
            }
            if (!/[0-9]{4}-[0-9]{2}-[0-9]{2}/i.test(startTime)) {
                startTime = currentLineReal[headers.indexOf(timeDimCode)]
            }
            endTime = _increaseTimeGranularityInterval(startTime, granularity);
        } else {
            startTime = lastTimeCondition.beginTime
            endTime = lastTimeCondition.endTime
            if (isAppendGran && !isMultiPeriod && (granularity === "hour" || granularity === "quarter"))
                endTime = _increaseTimeGranularityInterval(endTime, granularity);
        }
        return [startTime, endTime]
    }

    /**
     * 增加单个时间粒度区间
     * 1.因为周粒度和月粒度都把数据聚集在第一天的00:00:00，所以新增粒度区间为一天
     * @param startTime {String} 开始时间
     * @param granularity {String} 时间粒度
     * @return {String}
     */
    function _increaseTimeGranularityInterval(startTime, granularity) {
        var startDate = new Date(startTime.replace(/-/g, "/"))
        var startTimestamp = startDate.getTime()
        var endTimestamp
        switch (granularity) {
            case '5min': endTimestamp = startTimestamp + 5 * 60 * 1000;
                break
            case 'quarter':
                endTimestamp = startTimestamp + 15 * 60 * 1000;
                break
            case 'hour':
                endTimestamp = startTimestamp + 60 * 60 * 1000;
                break
            case 'date':
                endTimestamp = startTimestamp + 24 * 60 * 60 * 1000;
                break
            case 'week':
                endTimestamp = startTimestamp + 7 * 24 * 60 * 60 * 1000;
                break
            case 'month':
                endTimestamp = new Date(startDate.getFullYear(), startDate.getMonth() + 1, startDate.getDate()).getTime()
                break
            default:
                endTimestamp = startTimestamp + 24 * 60 * 60 * 1000;
                break
        }
        return new Date(endTimestamp).format('YYYY-MM-DD HH:MS:SS');
    }


    /**
     * rdk时间控件粒度配置适配器
     * @param {string} gap
     * @return {string}
     */
    function _rdkTimeGapAdapter(gap) {
        var pattern = /^([1-9]\d*)([dwm])$/
        if (pattern.test(gap)){
            var gapInfo = pattern.exec(gap)
            var number = Number(gapInfo[1]) > 0 ? Number(gapInfo[1]) - 1 : 0
            return number + gapInfo[2]
        }else{
            return "0d"
        }

    }

    /**
     * 挑选默认时间粒度
     * @param {{key:string, label:string, gap:string}[]} selectable 当前报表可选粒度
     * @param {string} defaultConfiguration 用户配置的默认粒度
     * @return {string}
     */
    function selectDefaultTimeGranularity(selectable, defaultConfiguration = "") {
        if (defaultConfiguration && selectable.findIndex(function (info) {
            return info.key === defaultConfiguration
        }) > -1) {
            return defaultConfiguration
        } else if (selectable.findIndex(function (info) {
            return info.key === "day"
        }) > -1) {
            return "day"
        } else {
            return selectable[0].key
        }
    }
     /**
     * 挑选当前报表可选粒度中在快速选择时间粒度数组中不为空的粒度
     * @param {{key:string, label:string, gap:string}[]} selectable 当前报表可选粒度
     * @param {Array[5][]} timeQuickSelectArr 多维数组 第一维数是5，第二位不确实
     * @return {{key:string, label:string, gap:string}[]}
     */

      function selectTimeGranularitySet(selectable,timeQuickSelectArr) {

        let newSelectable = selectable.filter(  item => {

         return timeQuickSelectArr[item.key].length > 0

        })
        if(newSelectable.length == 0)
        {
         
            return false;

        }
        return  newSelectable

}

    /**
     *  初始化时间控件的查询时间设置
     * @param {string} granularity 当前时间粒度
     * @param {string} defaultRange 当前默认时间间隔
     * @param {number} weekMode 周模式
     * @type {string} recentTime 哪里调用的该函数，快速选择和普通时间选择会不同
     * @return {{endDate: string, granularity: string, granularityItems, value: string[]}}
     */
    function initializeReportTimeSetting(granularity, defaultRange, weekMode = 0, type) {
        var startTime, endTime
        var timeSetting = {
            value: ["now", "now"],
            endDate: "now",
            granularity: granularity,
            granularityItems: rdkTimeRecentlyGranularityItems,
        }
        switch (granularity) {
            case "5min":
                timeSetting.minuteStep = 5;
                var minutes = Math.floor(new Date().getMinutes() / 5) * 5
                endTime = new Date().format('YYYY-MM-DD hh') + ":" + minutes + ":00";
                startTime = _calculateStartTime(new Date(endTime), defaultRange[defaultRange.length - 1], defaultRange.slice(0, defaultRange.length - 1)).format('YYYY-MM-DD hh:ms:ss')
                timeSetting.value = [startTime, endTime]
                timeSetting.granularity = "quarter"
                break
            case "15min":
                var quarter = Math.floor(new Date().getMinutes() / 15) * 15
                endTime = new Date().format('YYYY-MM-DD hh') + ":" + quarter + ":00";
                startTime = _calculateStartTime(new Date(endTime), defaultRange[defaultRange.length - 1], defaultRange.slice(0, defaultRange.length - 1)).format('YYYY-MM-DD hh:ms:ss');
                if(type === "recentTime"){
                    endTime = new Date((new Date(endTime)).getTime()-(1000*60*15)).format('YYYY-MM-DD hh:ms:ss');
                }
                timeSetting.value = [startTime, endTime];
                timeSetting.granularity = "quarter";
                break
            case "hour":
                startTime = _calculateStartTime(new Date(), defaultRange[defaultRange.length - 1], defaultRange.slice(0, defaultRange.length - 1)).format('YYYY-MM-DD hh') + ":00:00";
                endTime = new Date((new Date()).getTime()-(1000*60*60)).format('YYYY-MM-DD hh') + ":00:00";
                timeSetting.value = [startTime, endTime];
                break
            case "day":
                startTime = _calculateStartTime(new Date(), defaultRange[defaultRange.length - 1], defaultRange.slice(0, defaultRange.length - 1)).format('YYYY-MM-DD');
                endTime = _calculateStartTime(new Date(), "d", "1").format('YYYY-MM-DD hh:mm')
                timeSetting.value = [startTime, endTime];
                timeSetting.granularity = "date";
                break
            case "week":
                startTime = _calculateStartTime(new Date(), defaultRange[defaultRange.length - 1], defaultRange.slice(0, defaultRange.length - 1)).format('YYYY-MM-DD');
                endTime = new Date().format('YYYY-MM-DD');
                timeSetting.value = [startTime, endTime];
                timeSetting.weekStart = weekMode;
                break
            case "month":
                timeSetting.value = ["now-" + defaultRange, "now"];
                break
            default:
                break;
        }
        return timeSetting
    }

    /**
     * 初始化SQL报表时间控件设置
     * @param {{gap:string, timeOption:string}[]} initTimeOption 可选粒度
     * @param {string} defaultConfiguration 用户配置的默认粒度
     * @param {number} weekMode 周模式
     * @return {{weekStart: number, granularity: (string), selectGranularity: {gap: *, label: *, value: string}[], value: string[]}}
     */
    function initializeSQLReportTimeSetting(initTimeOption, defaultConfiguration = "", weekMode = 0) {
        var selectableGranularity = _getSqlTimeSelectGranularity(initTimeOption)
        var defaultGranularity = selectDefaultTimeGranularity(selectableGranularity, defaultConfiguration);
        var adapter = selectableGranularity.map(function (gr) {
            return {value: _adapterForRdkTime(gr.key), label: gr.label, gap: gr.gap}
        })
        return {
            value: ["now-1d", "now"],
            selectGranularity: adapter,
            granularity: _adapterForRdkTime(defaultGranularity),
            weekStart: weekMode
        };

    }

    /**
     * 正常粒度适配rdk控件要求
     * @param granularity
     * @return {string}
     */
    function _adapterForRdkTime(granularity) {
        switch (granularity) {
            case "15min":
                return "quarter";
            case "day":
                return "date";
            default:
                return granularity
        }
    }

    /**
     * 将rdk控件粒度还原为正常粒度
     * @param {string} granularity rdk控件粒度
     * @param minuteStep {number} 最小步进粒度
     * @return {string}
     */
    function restoredFromRdkTime(granularity, minuteStep) {
        switch (granularity) {
            case "quarter":
                return minuteStep===5?"5min":"15min";
            case "date":
                return "day";
            default:
                return granularity
        }
    }

    /**
     * 丰富报表的时间粒度信息
     * @param {string[]} timeOption 报表时间粒度集合
     * @return {{key:string, value:string, gap:string}[]}
     */
    function enrichGranularInformation(timeOption) {
        // 此部分兼容历史收藏报表存在"min"粒度
        var timeOptions = timeOption.map(function (gr) {
            return gr === "min" ? "15min" : gr
        })
        var granularPriority = {"15min": 0, "hour": 1, "day": 2, "week": 3, "month": 4};
        timeOptions.sort(function (x, y) {
            return granularPriority[x] - granularPriority[y]
        })
        return timeOptions.map(function (granular) {
            return granularityInformation.find(function (info) {
                return info.key === granular
            })
        })
    }

    /**
     * 丰富最近时间的选项信息
     * @param {string} recentConfig 业务配置中的最近时间配置项, 1d,7d,30d,1d
     * @return {{number: number, granularity: string, description: string}[]}
     */
    function enrichRecentTimeInformation(recentConfig) {

        var totalConfigs = recentConfig.split(",")
        var recentItems = totalConfigs.slice(0,3)
        var defaultRecent = totalConfigs.length === 4?totalConfigs[3]:recentItems[0]
        var legalItems = recentItems.filter(function (value) {
            return /^[1-9]\d*[hdwm]$/.test(value)
        })
        var protectDefaultRecent = legalItems.indexOf(defaultRecent) > -1 ?defaultRecent:legalItems[0]
        return legalItems.map(function (value) {
            var number = Number(value.slice(0, value.length - 1));
            return {
                number: number,
                granularity: value[value.length - 1],
                description: _transformGranularityUnitDescription(value[value.length - 1], number),
                defaultSelect: value === protectDefaultRecent
            }
        })
    }

    /**
     * 向前推算开始时间
     * @param {string} unit
     * @param {string} interval
     * @param {Date} endTime
     * @return {Date}
     */
    function _calculateStartTime(endTime, unit, interval) {
        switch (unit) {
            case "h":
                return new Date(endTime - Number(interval) * 60 * 60 * 1000)
            case "d":
                return new Date(endTime - Number(interval) * 24 * 60 * 60 * 1000)
            case "w":
                return new Date(endTime - Number(interval) * 7 * 24 * 60 * 60 * 1000)
            case "m":
                let startTime = new Date(endTime)
                let month = Number(interval)>0?endTime.getMonth() - Number(interval) + 1:endTime.getMonth()
                return new Date(startTime.setMonth(month));
        }
    }

    /**
     * 获取SQL报表可选粒度对象
     * @param {{gap:string, timeOption:string}[]} initTimeOption
     * @return {[{gap: string, label: string , key: string}]}
     */
    function _getSqlTimeSelectGranularity(initTimeOption) {
        var sqlTimeGap, selectGranularity
        if (initTimeOption && initTimeOption.length > 0) {
            sqlTimeGap = initTimeOption[0].gap
            if (initTimeOption[0].timeOption) {
                switch (initTimeOption[0].timeOption) {
                    case "week":
                        break;
                    case "month":
                        sqlTimeGap = "";
                        break
                    default:
                        sqlTimeGap = parseInt(sqlTimeGap) ? (parseInt(sqlTimeGap) - 1) + "d" : "0d";
                }
                selectGranularity = enrichGranularInformation(initTimeOption[0].timeOption.split("/")).map(function (info) {
                    info.gap = sqlTimeGap
                    return info
                })

            } else {
                selectGranularity = [{
                    label: i18n.report_day,
                    key: "day",
                    gap: parseInt(sqlTimeGap) ? (parseInt(sqlTimeGap) - 1) + "d" : "0d"
                }]
            }
        } else {
            selectGranularity = [{label: i18n.report_day, key: "day", gap: "0d"}]
        }
        return selectGranularity
    }


    /**
     * 转换 '粒度单位' 为中英文描述
     * @param {string} unit
     * @return {string}
     */
    function _transformGranularityUnitDescription(unit,number) {
        switch (unit) {
            case 'h':
                return addLastTimeS(i18n.report_hour,number);
            case 'd':
                return addLastTimeS(i18n.report_day,number);
            case 'w':
                return addLastTimeS(i18n.report_week,number);
            case 'm':
                return addLastTimeS(i18n.report_month,number);
            default:
                return unit
        }
    }

    function addLastTimeS(time, number) {
        if (number && number > 1 && i18n.locale === "enlabel") {
            return time + "s";
        }
        return time;
    }

    /* Started by AICoder, pid:fc7c5r1c4d458e8145c909c58049892ed6f7aad9 */
    /**
     * 根据默认查询范围限制最近时间的选项，以避免受查询性能影响。
     * @param {{"15min": {number: number, granularity: string, description: string}[]}} recentOption - 原最近时间选项。
     * @param {{"15min": "", "hour": "", "day": "", "week": "", "month": ""}} defaultRange - 各粒度查询范围。
     * @return {{"15min": {number: number, granularity: string, description: string}[]}} - 受限的最近时间选项。
     */
    function limitRecentTimeOption(recentOption, defaultRange) {
        for (const granularity in recentOption) {
            if (defaultRange[granularity]) {
                const now = new Date();
                const limitRange = defaultRange[granularity];
                const unit = limitRange[limitRange.length - 1];
                const interval = limitRange.slice(0, limitRange.length - 1);
                const limitTimestamp = _calculateStartTime(now, unit, interval);
                const recentList = recentOption[granularity];
                const limitRecentSelect = recentList.filter((recent) => {
                    const currentTimestamp = _calculateStartTime(now, recent.granularity, recent.number);
                    return currentTimestamp >= limitTimestamp;
                });
                // 如果最近时间粒度为空，则使用当前查询范围作为保护默认值。
                recentOption[granularity] = limitRecentSelect.length === 0 ?
                    [{ number: Number(interval), granularity: unit, description: _transformGranularityUnitDescription(unit, Number(interval)), defaultSelect: true }] :
                    limitRecentSelect;
            }
        }
        return recentOption;
    }
    /* Ended by AICoder, pid:fc7c5r1c4d458e8145c909c58049892ed6f7aad9 */

    function getRdkTimeGranularityGap(gap, index) {
        switch (index) {
            case 0:
            case 1:
            case 2:
                return rdkTimeControlGranularityItems[index].gap;
            default:
                return gap
        }
    }

    
    /* Started by AICoder, pid:60f451c5eb74cf1140e00aeb80257a7ff774d316 */
    /**
     * 根据输入字符串生成一个时间范围，确保结束时间在开始时间后15分钟内，并且不超过当天的23:59:59。
     *
     * @param {string} inputStr - 输入的时间字符串，格式为 "YYYY-MM-DD HH:mm:ss" 或其变体。
     * @returns {Array<string>} - 包含开始时间和结束时间的数组。
     */
    function getTimeRangeWith15MinLimit(inputStr, gap) {
        // 检查输入是否为空或非字符串
        if (!inputStr || typeof inputStr !== 'string') return ['', ''];

        // 去除首尾空格
        inputStr = inputStr.trim();

        // 分割日期和时间部分
        var parts = inputStr.split(' ');
        var datePart = parts[0];
        var timePart = parts[1] || '';

        // 补全日期，如果只有年月，则补全为年月日
        if (/^\d{4}-\d{2}$/.test(datePart)) {
            datePart += '-01';
        }

        // 补全时间部分
        if (!timePart) {
            timePart = '00:00:00';
        } else if (/^\d{2}$/.test(timePart)) {
            timePart += ':00:00';
        } else if (/^\d{2}:\d{2}$/.test(timePart)) {
            timePart += ':00';
        } else if (!/^\d{2}:\d{2}:\d{2}$/.test(timePart)) {
            // 回退到默认时间
            timePart = '00:00:00';
        }

        // 组合成完整的日期时间字符串
        var startTimeStr = datePart + ' ' + timePart;

        // Safari兼容：用 / 替代 -
        var startDate = new Date(startTimeStr.replace(/-/g, '/'));

        // 计算结束时间（开始时间加15分钟）
        var endDate = new Date(startDate.getTime() + 15 * 60 * 1000);

        // 设定最大时间 23:59:59
        var maxEndDate = new Date(startDate.getTime());
        maxEndDate.setHours(23);
        maxEndDate.setMinutes(59);
        maxEndDate.setSeconds(59);
        maxEndDate.setMilliseconds(0);

        // 如果结束时间超过最大时间，限制到23:59:59
        if (endDate.getTime() > maxEndDate.getTime()) {
            endDate = maxEndDate;
        }

        // 如果是天粒度直接结束时间为23:59:59
        if(gap === "date"){
            endDate = maxEndDate;
        }

        // 辅助函数：补零
        function padZero(num) {
            return num < 10 ? '0' + num : num;
        }

        // 辅助函数：格式化日期
        function formatDate(date) {
            return date.getFullYear() + '-' +
                padZero(date.getMonth() + 1) + '-' +
                padZero(date.getDate()) + ' ' +
                padZero(date.getHours()) + ':' +
                padZero(date.getMinutes()) + ':' +
                padZero(date.getSeconds());
        }

        // 返回格式化后的开始时间和结束时间
        return [formatDate(startDate), formatDate(endDate)];
    }
    /* Ended by AICoder, pid:60f451c5eb74cf1140e00aeb80257a7ff774d316 */
      
    /* Started by AICoder, pid:id2f22ff1444a8214528098fe0c50f110d730a1e */
    /**
     * 根据粒度调整时间：将传入的时间向后推一个粒度单位
     * @param {string} timeStr - 原始时间字符串（格式：YYYY-MM-DD HH:mm:ss）
     * @param {string} granularity - 粒度类型（如 'date'、'hour'、'5min'、'quarter'、'week'、'month'）
     * @returns {string} 新的时间字符串
     */
    function adjustEndTimeByGranularity(timeStr, granularity) {
        const date = new Date(timeStr.replace(/-/g, '/')); // 兼容不同浏览器的时间格式
    
        switch (granularity) {
            case 'date':
                date.setDate(date.getDate() + 1);
                break;
            case 'hour':
                date.setHours(date.getHours() + 1);
                break;
            case '5min':
                date.setMinutes(date.getMinutes() + 5);
                break;
            case 'quarter':
                date.setMinutes(date.getMinutes() + 15);
                break;
            case 'week':
                date.setDate(date.getDate() + 7);
                break;
            case 'month':
                date.setMonth(date.getMonth() + 1);
                break;
            default:
                break;
        }
    
        return date.format('YYYY-MM-DD HH:MS:SS');
    }

    /* Ended by AICoder, pid:id2f22ff1444a8214528098fe0c50f110d730a1e */ 
    


    return {
        enrichRecentTimeInformation: enrichRecentTimeInformation,
        timeComponentConstructor: timeComponentConstructor,
        enrichGranularInformation: enrichGranularInformation,
        restoredFromRdkTime: restoredFromRdkTime,
        initializeReportTimeSetting: initializeReportTimeSetting,
        selectDefaultTimeGranularity: selectDefaultTimeGranularity,
        selectTimeGranularitySet: selectTimeGranularitySet,
        initializeSQLReportTimeSetting: initializeSQLReportTimeSetting,
        getReportDrillTimeCondition: getReportDrillTimeCondition,
        limitRecentTimeOption: limitRecentTimeOption,
        getRdkTimeGranularityGap:getRdkTimeGranularityGap,
        getTimeRangeWith15MinLimit: getTimeRangeWith15MinLimit,
        adjustEndTimeByGranularity:adjustEndTimeByGranularity,

        _increaseTimeGranularityInterval:_increaseTimeGranularityInterval,
        _rdkTimeGapAdapter:_rdkTimeGapAdapter,
        _calculateStartTime:_calculateStartTime,
        _getSqlTimeSelectGranularity:_getSqlTimeSelectGranularity,
        _adapterForRdkTime:_adapterForRdkTime,
        _transformGranularityUnitDescription:_transformGranularityUnitDescription
    };
});
