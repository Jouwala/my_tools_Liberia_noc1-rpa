define([], function() {
    //这个文件定义了当前应用的功能函数，可以把常用的函数定义在这里方便复用。
    function destroyOrSave(modeule){//销毁全部modeule
        (modeule=='rdk.vrTable')?true:desModule(rdk.vrTable);
        (modeule=='rdk.vrDimension')?true:desModule(rdk.vrDimension);
        (modeule=='rdk.vrTarget')?true:desModule(rdk.vrTarget);
        (modeule=='rdk.vrSort')?true:desModule(rdk.vrSort);
        (modeule=='rdk.vrFilter')?true:desModule(rdk.vrFilter);
        (modeule=='rdk.simpleRptFields')?true:desModule(rdk.simpleRptFields);
        (modeule=='rdk.simpleRptTable')?true:desModule(rdk.simpleRptTable);
        (modeule=='rdk.twoAnalysis')?true:desModule(rdk.twoAnalysis);
        (modeule=='rdk.twoAnalysisDim')?true:desModule(rdk.twoAnalysisDim);
        (modeule=='rdk.twoAnalysisKpi')?true:desModule(rdk.twoAnalysisKpi);
        (modeule=='rdk.twoAnalysisSort')?true:desModule(rdk.twoAnalysisSort);
        (modeule=='rdk.twoAnalysisFilter')?true:desModule(rdk.twoAnalysisFilter);
    }
    function desModule(modeule) { 
        //销毁单个modeule
        if(modeule) modeule.destroyModule();
    }
    function setObjlength(obj){
        var i = 0;
        for(var p in obj){
            i= i + 1;
        };
        return i
    }
    //把data数组里的子对象的name属性，换成label属性
    function transitionProperty (data, name, label) {
        var arr = [],obj = {},len = data.length;
        for(var i = 0;i < len;i=i+1){
            obj[label] = data[i][name];
            arr.push(obj);
        }
        return arr
    }
    //给data对象创建一个target的属性，值复制属性init的值
    function copyType(data, init, target){
        var len,arr,obj;
        len = data.length;
        for (var i = 0; i < len; i=i+1) {
            for(p in data[i]){
                if(p == init){
                    data[i][target] = data[i][p];
                };
            };
        };
        return data
    }
    //把2个数组的每个值进行映射
    // [a,b][1,2]==>{a:1,b:2}
    function arrMapToObj(arr1,arr2){
        var len = arr1.length;
        var obj = {};
        for(var i = 0;i < len;i = i+1){
            obj[arr1[i]] = arr2[i];
        };
        return obj;
    }
    //把data数组里的子对象的start属性，换成end属性
    function transition(data, start, end){
        var len,arr,obj;
        len = data.length;
        arr = [];
        for(var i = 0;i < len;i = i + 1){
            obj = {};
            for(p in data[i]){
                if(p == start){
                    obj[end] = data[i][p];
                }else{
                    obj[p] = data[i][p];
                }
            }
            arr.push(obj)
        }
        return arr
    }
    //把data数组里的子数组的第start值，换成end
    function transitionValue(data, start, end){
        var len;
        len = data.length;
        for(var i = 0;i < len;i = i+1){
            data[i][start] = end(i);
        }
        return data
    }
    //给data数组里子对象key是p，且判断p的value是否为t,为t运行funt，否则funf
    function catalogOrtable(data, p, t, funt, funf){
        var len,arr;
        arr = [];
        len = data.length;
        for(var i = 0;i < len;i = i + 1){
            if(data[i][p]==t){
                funt(data[i])
            }else{
                funf(data[i])
            }
            arr.push(data[i]);
        }
        return arr
    }
    // 计算对象的lenght
    function getObjLenght(obj){
        var i = 0;
        for(p in obj){
            i = i+1;
        };
        return i
    }
    //给data里加一个key为p的value为value的对象，data是对象数组
    function appendKey(data, p, value){
        var len;
        len = data.length;
        for(var i = 0;i < len;i = i + 1){
            if(!data[i][p]){
                data[i][p] = value(i);
            }
        }
        return data
    }
    //往父数组arr里添加childObj对象，添加len个
    function appendData(arr, childObj, len){
        for(var i = 0; i < len; i = i + 1 ){
            var obj = childObj(i);
            arr.push(obj)
        }
        return arr;
    }
    //把对象数组data里的每一个对象key为p的值的value，取出来导出
    //[{id:1}] ==> [1]   这个如果data[i][p]为undefined会报错请用getArrObjlabelsStr()实现
    function getValue(data, p){
        var len,arr;
        arr = [];
        len = data.length;
        for(var i = 0;i < len;i=i+1){
            arr.push(data[i][p])
        }
        return arr
    }
    //去除undefined
    //[undefiend,1] ==> [1]
    function deleteUndefined(arr){
        var newArr = [];
        var len = arr.length;
        for(var i = 0;i < len;i = i+1){
            if(arr[i]!==undefined){
                newArr.push(arr[i])
            }
        }
        return newArr
    }
    /*
    * 功能：从数组对象中找出对象key的值==value的那个对象
    * 注：取出id==1的对象[{id:1}，{id:2}] ==> {id:1}只取出第一个
    * */
    function getArrObjKeyEqualValue(arr,key,value){
        return arr.filter(function(item){
            return item[key]==value;
        })[0];
    }
    //搜索一组数组对象中找出符合要求的数据
    function filter(data, value, key){
        var len;
        len = data.length;
        for(var i=0;i<len;i=i+1){
            if(data[i][key].indexOf(value)!==-1){
                continue
            }else{
                delete data[i];
            }
        }
        data = deleteUndefined(data);
        return data
    }
    //从一个数组里把数据放到另一个数组的某个对象的属性里
    function getKeyToArr(parentObj,childArr,parValue,chiidValue,parConValue){
        var len = childArr.length;
        for(var i=0;i<len;i=i+1){
            if(parentObj[parValue]==childArr[i][chiidValue]){
                parentObj[parConValue].push(childArr[i]);
            }
        }
    }
    //一个数组对象的arr里，调取对象里value为label的那个对象
    //[{id:1}，{id:2}] ==> [{id:1}]只取出第一个
    function getArrObjLabel (label,arr){
        var len = arr.length;
        var newArr = [];
        for(var i=0;i<len;i=i+1){
            for(p in arr[i]){
                if(arr[i][p]==label){
                    newArr.push(arr[i]);
                    return newArr
                }
            }
        }
    }
    //去除数组对象里label=2的那个对象
    // [{id:1}，{id:2}] ==> [{id:1}]
    function deleteArrLabelObj(arr,label){
        var len = arr.length;
        var newArr = [];
        for(var i=0;i<len;i=i+1){
            for(p in arr[i]){
                if(arr[i][p]!==label){
                    newArr.push(arr[i]);
                }
            }
        }
        return newArr
    }
    //去除数组对象里key=label的那个对象
    // [{id:1}，{label:2}] ==> [{id:1}]
    function deleteArrKeyObj(arr,label){
        var len = arr.length;
        var newArr = [];
        for(var i=0;i<len;i=i+1){
            for(p in arr[i]){
                if(p!==label){
                    newArr.push(arr[i]);
                }
            }
        }
        return newArr
    }
    //一个arr数组对象里，取出每个对象key为key的值组成数组
    //[{id:1}，{id:2}] ==> [1,2]
    function getArrObjlabelsStr(arr, key){
        var len = arr.length;
        var newArr = [];
        for(var i = 0; i< len;i++){
            for(p in arr[i]){
                if(p == key){
                    newArr.push(arr[i][key])
                }
            }
        }
        return newArr
    }
    //一个对象里，取出每个key为key的值
    //{id:1,name:2}==>1
    function getObjLabel(obj, key){
        for(p in obj){
            if(p == key){
                return obj[p];
            };
        };
    }
    //从一个数组里取出对应数组index的几个传到另一个数组
    //[1,3,2,4,5,6,7],[2,4] ==> [2,5]
    function appendArrIndex(arrIndex, data){
        var len,arr; 
        len = arrIndex.length;
        arr = [];
        for(var i = 0;i < len;i = i+1){
            arr.push(data[arrIndex[i]])
        }
        return arr
    }
    //取出2维数组里每一个数组的第n个值到别的数组
    //[[1,2],[3,4]] 1 ==> [2,4]
    function appendArrChild(data,index){
        var arr = [];
        var len = data.length;
        for(var i = 0;i < len;i = i+1){
            arr.push(data[i][index]);
        }
        return arr
    }
    //给data里加一个key为p,value为arr[0]的对象，data是对象数组
    //给空数组根据value的数量创建
    //[] ==> [{p:arr[0]}]
    function appendKey1(arr, p){
        var len = arr.length,data = [];
        for(var i = 0;i < len;i = i + 1){
            var obj = {};
            obj[p] = arr[i];
            data.push(obj);
        }
        return data
    }
    //给数组对象添加属性和值为从0开始的序列
    //[{v:value}] ==> [{v:value,p:0}]
    function appendKey2(data, p){
        var len;
        len = data.length;
        for(var i = 0;i < len;i = i + 1){
            if(!data[i][p]){
                data[i][p] = i;
            }
        }
        return data
    }
    //给数组对象添加属性和值value是一个数组
    //[{v:value}],[5,8] ==> [{v:value,p:5,p:8}]
    function appendKey3(data, p, value){
        var len;
        len = data.length;
        for(var i = 0;i < len;i = i + 1){
            if(!data[i][p]){
                data[i][p] = value[i];
            }
        }
        return data
    }
    //删除所有空module
    function deleteAllHollowModule(scope,EventService){
        var panId = scope.tabPrefix + '_graphsModule';//父元素的id
        var box = $('#' + panId);//容器
        var divs = $('#' + panId).children('div'); // 子集合
        var len = divs.length;//div个数
        for(var i = 0;i < len;i = i+1){
            if(!$(divs[i]).children("div").length){
                var id = $(divs[i]).attr("id");
                var index;
                var obj = {
                    bar : id.indexOf("barModule_"),
                    pie : id.indexOf("pieModule_"),
                    line: id.indexOf("lineModule_"),
                    normal: id.indexOf("normalModule_"),
                };
                for(var p in obj){
                    if(obj[p]!==-1){
                        index = obj[p];
                        var moduleName = id.slice(index);
                        var moduleNameIndex = moduleName.indexOf("_") + 1;
                        var moduleReallyName = moduleName.slice(0,moduleNameIndex);
                        var moduleIndex = index + moduleReallyName.length;
                        break
                    };
                };
                var nub = parseInt(id.slice(moduleIndex));
                var Mindex = id.indexOf("Module");
                var type = id.substr(index,Mindex - index);
                var typeObj = {};
                typeObj[type] = nub;
                //删除图形module
                EventService.broadcast('del_graphMol', 'delGraphMol', typeObj);
                // scope.parentScope.graphs[type].splice(nub,1);
                $(divs[i]).remove();
            };
        };
        // 当删除的是最后一个的时候把上下滚动条消除
        deleteImgDivGraph(scope, EventService);
    }
    function deleteImgDivGraph(scope, EventService){
        var panId = scope.tabPrefix + '_graphsModule';//父元素的id
        var box = $('#' + panId);//容器
        var divs = $('#' + panId).children('div'); // 子集合
        var len = divs.length;//div个数
        if(len == 0){
            //关闭图形
            EventService.broadcast('close_graph', 'closeGraph');
        };
    }
    // 滑动的效果
    function initDelGraphPosition(scope){
        var panId = scope.tabPrefix + '_graphsModule';//父元素的id
        var box = $('#' + panId);//容器
        var boxWidth = $('#' + panId).innerWidth(); //容器宽

        var divs = $('#' + panId).children('div');// 子集合
        var len = divs.length;//div个数
        var divWidth = parseInt(boxWidth/2,10);//每一个子的宽

        var exposeWidth = parseInt(boxWidth/(2*(len-1)),10);  //  遮住的宽
        var slidingDistance = divWidth - exposeWidth;//滑动距离；
        //初始化位置
        function init(){
            if(!divs[0]){return};
            divs[0].style.left = 0;
            for(var j = 1;j < len;j = j+1){
                divs[j].style.left = divWidth + exposeWidth * (j - 1) + 'px';
            }
        };
        init();
        for(var i = 0;i < len;i = i + 1){
            (function(i){
                divs[i].addEventListener("mouseover",divMouseover,false);
                function divMouseover(){
                    init();
                    for(var j = 1;j <= i;j=j+1){
                        divs[j].style.left = parseInt(divs[j].style.left,10) - slidingDistance + 'px';
                    };
                }
            }(i));
        };
    }
    // 取出对象的每一个属性的值
    //obj={key:1,key2:2,key3:3}==>[1,2,3]
    function getObjLableToArr(obj){
        var arr = [];
        for(var p in obj){
            arr.push(obj[p]);
        };
        return arr
    }
    // 从对象里删除key为key的属性
    //obj={key:1,key2:2,key3:3}==>{key:1,key3:3}
    function deleteObjKey(obj,key){
        var newObj = {}
        for(var p in obj){
            if(p!==key){
                newObj[p] = obj[p];
            };
        };
        return newObj
    }
    // 去除数组对象里id为label的那一个
    function deleteArrItem(arr, id, label){
        var newArr = [];
        var len = arr.length;
        for(var i =0; i < len; i = i+1){
            if(arr[i][id] !== label){
                newArr.push(arr[i])
            };
        };
        return newArr;
    }
    //获取元素在数组中的下标
    function getIndexOfArray(arr,elem){
        for(var i=0,len=arr.length;i<len;i++){
            if(arr[i]==elem){
                return i;
            }
        }
        return -1;
    }
//获取二维数组指定列不重复数据
    function getUnique(index,array){
        if(index < 0){
            console.log('params error');
            return res;
        }

        var allLegendArr = array.map(function(item){return item[index];});
        return uniquel(allLegendArr);
    }

    function getXUnique(index,array){
        var res = [], hash = {};
        if(index<0){
            console.log('params error');
            return res;
        }
        var len = array.length;
        for(var i=0, elem;i < len &&(elem = array[i][index]) != null; i++)  {
            if (!hash[elem]){
                res.push(elem);
                hash[elem] = true;
            }
        }
        return res;
    }

    //初始化二维数组元素为0
    function initBarGraphData(row,column){
        var barGraphData=[];
        for(var i=0;i<row;i++){
            barGraphData[i]=[];
            for (var j=0;j<column;j++){
                barGraphData[i][j]=0;
            }
        }
        return barGraphData;
    }
    
    //获取柱状图图形数据
    function getBarGraphData(data,graphHeader,graphLegend,barGraphData,index,topN,legendIndex,xIndex,kpiUnit,graphType){
        var temData = [];
        var xData = [];
        var xAndLegend = [];
        var dataLen = data.length;
        var xArrayLen = graphHeader.length;
        var legendLen = graphLegend.length;
        for (var i=0;i<dataLen;i++){
            for(var j=0;j<xArrayLen;j++){
                for(var k=0;k<legendLen;k++){
                    if (graphType != 'normal' && data[i][xIndex]==graphHeader[j] && data[i][legendIndex]==graphLegend[k]){
                        if(kpiUnit == "%" && temData.indexOf(data[i][legendIndex]) != -1 && xData.indexOf(graphHeader[j]) != -1 && xAndLegend.indexOf(data[i][legendIndex]+graphHeader[j]) != -1){
                            continue;
                        }
                        // barGraphData[k][j]+=Number(data[i][index]);
                        /* Started by AICoder, pid:f6ad204a93o19ff149510813a0e82e1d65e33995 */
                        // 计算新的值并保留两位小数
                        var newValue = (Number(barGraphData[k][j]) + Number(data[i][index])).toFixed(2);

                        // 将其转换为数字，以便自动去除不必要的小数部分
                        newValue = parseFloat(newValue);

                        // 如果是整数，去掉小数部分
                        if (newValue % 1 === 0) {
                            newValue = Math.floor(newValue);
                        }

                        // 更新 barGraphData
                        barGraphData[k][j] = newValue;
                        /* Ended by AICoder, pid:f6ad204a93o19ff149510813a0e82e1d65e33995 */
                        temData.push(data[i][legendIndex]);
                        xData.push(graphHeader[j]);
                        xAndLegend.push(data[i][legendIndex]+graphHeader[j]);
                    } else if (graphType == 'normal' && data[i][legendIndex]==graphLegend[k] && graphHeader[j] <= parseFloat(data[i][xIndex])  && parseFloat(data[i][xIndex]) < graphHeader[j+1]){
                        barGraphData[k][j] += 1;
                        temData.push(data[i][legendIndex]);
                    }

                }
            }
        }
    }
    /*
        功能: 获取饼图数据
        注：isAdd为新添加参数 hhn 2019-1-24
    */
    function getPieGraphData(data,graphLegend,legendIndex,index,topN,isAdd,kpiUnit){
        var temData = [];
        //初始化数组
        var pieGraphData=[];
        var graphLegendLenght = graphLegend.length;
        for(var i = 0;i < graphLegendLenght; i++){
            pieGraphData[i]=0;
        }
        var dataLen = data.length;
        for (var i = 0; i < dataLen;i++){
            for(var j=0;j<graphLegend.length;j++){
                if (data[i][legendIndex] == graphLegend[j]){
                    if(kpiUnit == "%" && temData.indexOf(data[i][legendIndex]) != -1){
                        continue;
                    }
                    /* Started by AICoder, pid:r5ce5ze08f03c361492e0946f0692d15bff40796 */
                    // 假设 pieGraphData[j] 已经通过之前的计算得到了一个新的值
                    var newValue = (Number(pieGraphData[j]) + Number(data[i][index])).toFixed(2);

                    // 将字符串转换为数字
                    newValue = parseFloat(newValue);

                    // 检查是否是整数
                    if (newValue % 1 === 0) {
                        // 如果是整数，去掉小数部分
                        newValue = Math.floor(newValue);
                    }

                    // 更新 pieGraphData[j]
                    pieGraphData[j] = newValue;
                    /* Ended by AICoder, pid:r5ce5ze08f03c361492e0946f0692d15bff40796 */                
                    temData.push(data[i][legendIndex]);
                }
            }
        }
        // data:[
        //     {value:335, name:'2017-03-16 10:30:00.0'},
        //     {value:310, name:'邮件营销'},
        //     {value:234, name:'联盟广告'},
        //     {value:135, name:'视频广告'},
        //     {value:1548, name:'搜索引擎'}
        // ],
        pieGraphData = conversionPieDataFormat(pieGraphData,graphLegend);

        //此处添加other的数据和图例 hhn 2019-1-24
        if(isAdd){
            var otherData = 0;
            var len = data.length;
            for(var a = 0;a < len;a = a + 1 ){
                otherData = otherData + Number(data[a][index]);
            }
            
            pieGraphData.forEach(function(item){
                otherData = otherData - item.value;
            });

            pieGraphData.push({value:otherData,name:"Other"})
        }
        return pieGraphData;
    }
    function getGraphData(metadata, request){
        //获取图形设置入参
        var x=request.graph.x;
        var y=request.graph.y;
        var graphType=request.graph.graphType;
        var graphTitle=request.graph.title;
        var graphLegend=request.graph.legend;
        var graphInfo=request.graph.info;
        var graphShowName=request.graph.showName;
        var topN=request.graph.top;
        var iterval = request.graph.interval;
        var YStyle = request.graph.YStyle;
        
        var result = metadata;
        //获取图列描述
        var legendIndex=getIndexOfArray(result.header,graphLegend);
        var allLegendArr = getUnique(legendIndex,result.data);
        var graphLegendArray= allLegendArr.slice(0,topN);
        // 新加判断添加other     hhn   2019-1-24
        var isAdd = isAddOther(allLegendArr,topN);
        var yIndex=getIndexOfArray(result.header,y);
        //获取指标单位
        var kpiUnit = getKpiUnit(y,result.field,result.header,result.kpiUnit);
        //定义返回数据json对象
        var graphData={};
        if (graphType=='bar' || graphType=='line'){
            //获取x信息
            var xIndex=getIndexOfArray(result.header,x);
            var xArray=getXUnique(xIndex,result.data,topN);
            //对x轴做一个由小到大的排序
            xArray.sort(function(a,b){
                //区分字符串是时间格式还是其他
                if(a.match(/\d{4}-\d{2}-\d{2}/)){
                    return new Date(a.replace(/-/g,"/")).getTime()-new Date(b.replace(/-/g,"/")).getTime();
                }else{
                    return a-b;
                }
            })
            //初始化graphData二维数组
            var barGraphData=initBarGraphData(graphLegendArray.length,xArray.length);
            //获取柱状图二维数组数据
            getBarGraphData(result.data,xArray,graphLegendArray,barGraphData,yIndex,topN,legendIndex,xIndex,kpiUnit,graphType);
            graphData.title=graphTitle;
            graphData.legend=graphLegendArray;
            graphData.header=xArray;
            graphData.data=barGraphData;
            graphData.unit=kpiUnit;
        } else if (graphType == 'normal') {
            //获取x信息
            var xIndex = getIndexOfArray(result.header,x);
            var allLegendArr = getUnique(xIndex,result.data);
            var xArray= allLegendArr.slice(0,topN); 
            //对x轴做一个由小到大的排序
            xArray.sort(function(a,b){
                    return a-b;
            })
            var startArr = xArray[0];
            var endArr = xArray[xArray.length - 1];
            // 最大值向上，最小值向下，差值再向上取整
            var len = Math.ceil((Math.ceil(endArr) - Math.floor(startArr)) / iterval) + 2;
            var arrTemp = Array.from(new Array(len));
            var xArray = arrTemp.map(function (value, idx) {
                return Math.floor(parseFloat(startArr) + parseFloat(iterval) * idx);
            });

            //初始化graphData二维数组
            var barGraphData = initBarGraphData(graphLegendArray.length,xArray.length);
            //获取柱状图二维数组数据
            getBarGraphData(result.data,xArray,graphLegendArray,barGraphData,yIndex,topN,legendIndex,xIndex,kpiUnit,graphType);
            graphData.title = graphTitle;
            graphData.legend = graphLegendArray;
            graphData.header = xArray;
            // graphData.data = barGraphData;
            graphData.data = ['样本数','Samples'].includes(YStyle) ? barGraphData: getProportionData(barGraphData);
            graphData.unit = kpiUnit;
        } else if (graphType=='pie'){
            

            //获取饼图数据数据
            var pieGraphData=getPieGraphData(result.data,graphLegendArray,legendIndex,yIndex,topN,isAdd,kpiUnit);//isAdd为新添加参数 hhn 2019-1-24
            //拼成需要的数据格式
        
            graphData.title=graphTitle;

            //legend因为添加了other所以需要进行判断和重新赋值 hhn  2019-1-24
            if(isAdd){
                graphLegendArray.push('Other');
            }
            graphData.legend=graphLegendArray;

            graphData.data=pieGraphData;
        }
        return graphData;   
    }

    /* Y轴数据转为占比 */
    function getProportionData(barGraphData){
        //遍历
        var graphDataArr = [];
        for (var idx = 0; idx < barGraphData.length; idx++){
            var data = barGraphData[idx];
            var total = eval(data.join('+'));
            var resultArr = [];
            for (var i = 0; i < data.length ;i++){
                var percent = total == 0 ? 100: Math.floor((data[i] / total)*100);
                resultArr.push(percent);
            }
            graphDataArr.push(resultArr);
        }
        return graphDataArr;
    }
    
    function getKpiUnit(kpi,fields,headers,kpiUnit){
        var index = 0;
        for(var i=0;i<headers.length;i++){
            if(headers[i] == kpi){
                index = i;
                break;
            }
        }
        for(var i=0;i<kpiUnit.length;i++){
            if(fields[index].indexOf(kpiUnit[i].key) != -1){
                return kpiUnit[i].baseUnit.unitName; 
            }
        }
        return "0";
    }
    
    /*
        功能: 判断是否添加other，
        注：只有选择的top数小于data总数时才需要添加other
    */
    function isAddOther(data,top) {
        if(data.length>top){
            return true
        }
        return false
    }
    function conversionPieDataFormat(data,legend){
        var arr = [];
        var len = data.length;
        for(var i = 0;i < len;i = i+1){
            var obj = {};
            obj.value = data[i];
            obj.name = legend[i];
            arr.push(obj);
        }
        return arr;
    }
    function setTableHeight(scope){
        var conditionHei,graphH = 0;
        var switchH = 13;
        var buttonH = 57;
        var recordsH = 34;
        var parentHeight = $("#" + (scope.tabPrefix + "_reportPage")).height();
        var condition = $("#" + (scope.tabPrefix + "_flexible"));
        condition.attr('style').indexOf("display: none")!==-1?conditionHei = 0:conditionHei = condition.height();
        var graph = $("#" + (scope.tabPrefix + '_graphsModule'));
        if(graph.attr('style')){
            graph.attr('style').indexOf("display: none")!==-1?graphH = 0:graphH = graph.height();
        };
        var heightVal = parentHeight - conditionHei - graphH - (switchH * 2) - buttonH - recordsH - 10;
        var tableH = heightVal + 38 + 'px';
        if(parseInt(tableH) <= 0){tableH = 0;};
        $("#" + (scope.tabPrefix + '_ds4reportTable')).height(tableH);
        /*新增10条的时候添加一个最大高度345*/
        if(scope.currentPageSize==10){
            _id(scope.tabPrefix + '_ds4reportTable').style.maxHeight="345px";
        }
        var tableWrap = document.querySelector('#' + scope.tabPrefix + '_ds4reportTable .rdk-table-module .wrapper');
        var tableWrapH = heightVal- 32+ 'px';
        //!!tableWrap && $(tableWrap).height(tableWrapH);
        if(!!tableWrap){
            tableWrap.style.maxHeight=tableWrapH;
        }
    }
    function generateID(){
        var d = new Date();
        var id = d.getTime();
        return id;
    }
    function _id(id){
        return document.getElementById(id);
    }
    //校验是否含有特殊字符,如果含有特殊字符则返回true
    function check_other_char(str){
        var arr=["&","\\","/","*",">","<","#","!"];
        var filterArr=arr.filter(function(item){
            return str.indexOf(item)>=0;
        })
        return filterArr.length>0
    }
    function _initHeight(id){
        $(id).height("100%").siblings().height("0");
    }
    function getMonDay(datevalue){
        var dateValue=datevalue;
        var arr=dateValue.split('-');
        var date=new Date(arr[0],arr[1]-1,arr[2]);
        var dateOfWeek=date.getDay();
        var dateOfWeekInt=parseInt(dateOfWeek,10);
        if(dateOfWeekInt==0){
            dateOfWeekInt=7;
        }
        var aa=7-dateOfWeekInt;
        var temp2=parseInt(arr[2],10);
        var sunDay=temp2+aa;
        var monDay=sunDay-6;
        var startDate=new Date(arr[0],arr[1]-1,monDay);
        var sm=parseInt(startDate.getMonth())+1;
        var start=startDate.getFullYear()+'-'+sm+'-'+startDate.getDate();
        return start;
    }
    /*
       功能: 复制数组
    */
    function copyArr(arr){
        return arr.slice(0);
    }
    /*
    * 功能：数组去重
    * */
    function uniquel(arr){
        var hash=[];
        for (var i = 0; i < arr.length; i++) {
            if(hash.indexOf(arr[i])==-1){
                hash.push(arr[i]);
            }
        }
        return hash;
    }
    /*
       功能: 复制对象
    */
    function copyObj(obj){
        var objStr = JSON.stringify(obj);
        return JSON.parse(objStr);
    }
    
    function getClass(o) { 
        return Object.prototype.toString.call(o).slice(8, -1);
    }
    
    //深拷贝
    function deepCopy(obj) {
        var result, oClass = getClass(obj);

        if (oClass == "Object") result = {}; 
        else if (oClass == "Array") result = []; 
        else return obj; 

        for (var i in obj) {
            var copy = obj[i];

            if (getClass(copy) == "Object") result[i] = deepCopy(copy); 
            else if (getClass(copy) == "Array") result[i] = deepCopy(copy); 
            else result[i] = copy;
        }

        return result;
    }
    
    /*
       功能: 加载拖拉分割线
       id：拖拉分割线的id
    */
    function getSplitBar(id, EventService, type){
        var 
            _dragStartX,
            _dragEndY,
            _previousElement,
            _nextElement,
            _splitBar,
            _parent;

            //分割条元素和父元素
            _splitBar = _id(id);
            _parent = _splitBar.parentNode;

            setSplitBarHeight();
            del_ff(_parent);
            //上一个元素和下一个元素
            _previousElement = _splitBar.previousSibling;
            _previousPreviousElement = _previousElement.previousSibling;
            _nextElement = _splitBar.nextSibling;
            //点击和松开鼠标触发事件
            _splitBar.ondragstart = clickSplitBar;
            _splitBar.ondragend = mouseDownHandle;
            _splitBar.onclick = hideLiftTree;
            /*
                功能: 根据父元素的高度计算分隔条的高度
            */
            function setSplitBarHeight(){
                _splitBar.style.height = _parent.clientHeight + 'px';
            }
            /*
                功能: 鼠标点击分隔条触发拖拉事件
                event：当前事件，用于获取鼠标的x坐标和y坐标
                _dragStartX:用于记录分割线的开始位置
            */
            function clickSplitBar(event){
              _dragStartX = event.clientX;
            }
            /*
                功能: 鼠标松开分隔条触发事件
                event：当前事件，用于获取鼠标的x坐标和y坐标
                _dragEndY:用于记录分割线的结束位置
            */
            function mouseDownHandle(event){
                EventService.broadcast("graph",EventService.RESIZE);
                _dragEndY = event.clientX;
                var offsetX = protectElementWidth(_previousElement, _nextElement,  _dragStartX - _dragEndY);
                var _previousElementWidth = _previousElement.clientWidth - offsetX;
                var _nextElementWidth = _nextElement.clientWidth + offsetX;
                //因为浏览器问题有些会出现小数；所以要做个特殊处理；判断总width是不是大于父元素
                if((_parent.clientWidth - 1) < (_previousElementWidth + _nextElementWidth)){
                    _previousElement.style.width = (_previousElementWidth - 1) +"px";
                    _nextElement.style.width = (_nextElementWidth - 1) + "px";
                    return;
                }
                _previousElement.style.width = _previousElementWidth +"px";
                _nextElement.style.width = _nextElementWidth + "px";
            }

            function protectElementWidth(_previousElement, _nextElement, offsetX){
                var previous = _previousElement.clientWidth - offsetX;
                previous < 100 ? offsetX = _previousElement.clientWidth - 100 : true;

                var next = _nextElement.clientWidth + offsetX;
                next < 100 ? offsetX =  100 - _nextElement.clientWidth : true;

                return offsetX;
            }
            /*
            *  功能：隐藏左边的树
            * */
            function hideLiftTree(event){
                //谷歌95版本，浏览器兼容处理
                var element = event.toElement;
                if(!element){
                    element = event.target;
                }
                EventService.broadcast("graph",EventService.RESIZE);
                if(_previousElement.clientWidth === 0){
                    _previousElement.style.width = "20%";
                    
                    if(_previousPreviousElement != null && typeof _previousPreviousElement != "undefined"){
                     _previousPreviousElement.style.width = "40px";
                     _nextElement.style.width = "calc(80% - 45px)";
                    }else{
                       _nextElement.style.width = "calc(80% - 10px)";
                    }

                    $(element).css("left","auto");
                    $(element).removeClass("glyphicon-chevron-right");
                    $(element).addClass("glyphicon-chevron-left");
                    return;
                }
                _previousElement.style.width = "0";
                _nextElement.style.width = "100%";
                if(_previousPreviousElement != null && typeof _previousPreviousElement != "undefined"){
                    _previousPreviousElement.style.width = "0";
                }
                
                $("#reportTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $("#kpiTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $("#taskTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $(element).css("left","0");
                $(element).removeClass("glyphicon-chevron-left");
                $(element).addClass("glyphicon-chevron-right");
            }
            /*
                功能: 浏览器兼容，去除元素之间的‘空格’和‘文字’，只保留标签
                注：谷歌还要去除注释nodeName == "#comment"，这里因为删除元素后，它的length会改变，所以要用递归。
            */
            function del_ff(elem){
              var elem_child = elem.childNodes;
              for(var i=0; i<elem_child.length;i++){
                if((elem_child[i].nodeName == "#text" && !/\s/.test(elem_child.nodeValue))||(elem_child[i].nodeName == "#comment")){
                  elem.removeChild(elem_child[i]);
                  return del_ff(elem);
                }
              }
            }

            if(type === "liu"){
                _splitBar.ondragend = mouseDownHandle2;
                _splitBar.onclick = hideLiftTree2;
            }

            function mouseDownHandle2(event){
                EventService.broadcast("graph",EventService.RESIZE);
                _dragEndY = event.clientX;
                var offsetX = protectElementWidth(_previousElement, _nextElement,  _dragStartX - _dragEndY);
                var _previousElementWidth = _previousElement.clientWidth - offsetX;
                var _nextElementWidth = _nextElement.clientWidth + offsetX;
                //因为浏览器问题有些会出现小数；所以要做个特殊处理；判断总width是不是大于父元素
                if((_parent.clientWidth - 1) < (_previousElementWidth + _nextElementWidth)){
                    _previousElement.style.width = (_previousElementWidth - 1) +"px";
                    _nextElement.style.marginLeft = (_previousElementWidth + 10) + "px";
                    return;
                }
                _previousElement.style.width = _previousElementWidth +"px";
                _nextElement.style.marginLeft = (_previousElementWidth + 10) + "px";
            }

            function hideLiftTree2(event){
                //谷歌95版本，浏览器兼容处理
                var element = event.toElement;
                if(!element){
                    element = event.target;
                }
                EventService.broadcast("graph",EventService.RESIZE);
                if(_previousElement.clientWidth === 0){
                    _previousElement.style.width = "300px";
                    _previousElement.style.overflow = "auto";
                    _nextElement.style.marginLeft = "310px";
                    $(element).css("left","auto");
                    $(element).removeClass("glyphicon-chevron-right");
                    $(element).addClass("glyphicon-chevron-left");
                    return;
                }
                _previousElement.style.width = "0";
                _previousElement.style.overflow = "hidden";
                _nextElement.style.marginLeft = "10px";
                
                $("#reportTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $("#kpiTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $("#taskTab .tabs .rdk-tabs-wrap ul").css("width","100%");
                $(element).css("left","0");
                $(element).removeClass("glyphicon-chevron-left");
                $(element).addClass("glyphicon-chevron-right");
            }
        
    }
    //单击收缩图形        
    function clkShowPanel($event,elemId) {
        var flexible = document.getElementById(elemId);
        $(flexible).slideToggle("slow", function () {
            if (!$event) {
                $(flexible).next().children().removeClass().addClass('btn-icon-up btn-show btn-icon-down');
                return;
            }                   
            $event.target.className.indexOf('btn-icon-up') !== -1 ? $event.target.className = 'btn-show btn-icon-down' : $event.target.className = 'btn-icon-up btn-show btn-icon-down';
        });
    }
    //根据粒度处理时间格式
    function timeFormat(time,timeGranularity){
        switch (timeGranularity){
            case '5min':
            case '15min':
            case 'quarter':
                return time.substring(0,time.length-3);
            case 'hour':
                return time.substring(0,time.length-6);
            case 'day':
            case 'date':
                return time.split(" ")[0];
            case 'week':
                return time.split(" ")[0];
            case 'month':
                return time.substring(0,7);
            default:
                return time;
        }
    }
    //判断是否为时间格式（YYYY-MM-DD HH:MM:SS）
    function isDateFormat(str){
        var flag = true;
        var reg = /^(\d{1,4})(-|\/)(\d{1,2})\2(\d{1,2}) (\d{1,2}):(\d{1,2}):(\d{1,2})$/;
        var result = (str + "").match(reg);
        if(result == null){
            flag = false;
        }
        return flag;
    }
    //当文本内容超过规定长度时按单词换行
    function newLineProcess(data,maxLength){
        var dataArray = data.split(" ");
        var newData = [];
        while(dataArray.length > 0){
            var lineLength = 0;
            var temp = "";
            var wordNum = dataArray.length;
            for(var i=0;i<wordNum;i++){
                lineLength += dataArray[i].length;
                lineLength = (i == wordNum-1 ? lineLength : lineLength + 1);
                if(lineLength <= maxLength || i == 0){
                    temp += dataArray[i] + " ";
                }
                if(lineLength > maxLength || i == wordNum - 1) {
                    temp = temp.substring(0,temp.length - 1);
                    newData.push(temp);
                    switch(i){
                        case 0:
                            dataArray.splice(0,1);
                            break;
                        case wordNum-1:
                            lineLength <= maxLength ? dataArray.splice(0,wordNum) : dataArray.splice(0,i);
                            break;
                        default:
                            dataArray.splice(0,i);
                            break;
                    }
                    break;
                }
            }
        }
        return newData.join("\n");
    }
    //折线图、柱状图图例设置
    function getLegend(legendParams){
        var legendData = legendParams.legendData;
        var exceedLegendNum = legendParams.exceedLegendNum;
        var notExceedLegendNum = legendParams.notExceedLegendNum;
        var maxLegendLength = legendParams.maxLegendLength;
        var decideNum = legendParams.decideNum;
        var itemWidth = legendParams.itemWidth;
        
        var newLegend = [];
        var totalLegendNum = legendData.length;
        var dataIndex = [];
        var lineIndex = 0;
        //每行最多显示的图例个数
        var maxEachLineNum = Math.round(totalLegendNum / decideNum);
        //当图例个数少时尽可能显示完整
        if(totalLegendNum <= notExceedLegendNum){
            maxEachLineNum = totalLegendNum;
        }
        for(var i=0; i<totalLegendNum; i++){
            dataIndex.push(legendData[i]);
            if((i+1) % maxEachLineNum == 0 || (i+1) == totalLegendNum){
                var legendObj = {
                    x:'right',
                    y:'center',
                    padding:[5,140,0,0],
                    itemGap:10,
                    itemHeight:10,
                    itemWidth:itemWidth,
                    tooltip :{
                        show:true
                    },
                    top:lineIndex*6+'%',
                    formatter: function(params) {
                        if(maxEachLineNum > exceedLegendNum && params.length > maxLegendLength){
                            return params.substring(0,maxLegendLength - 1)+'...';
                        } else {
                            return params;
                        }
                    },
                    data : dataIndex
                };
                newLegend.push(legendObj);
                dataIndex = [];
                lineIndex++;
            }
        }
        return newLegend;
    }

    //环形图图例设置
    function getPieLegends(legendData,maxLength,left,fontSize){
        var legendNum = legendData.length;
        var colMaxNum = Math.ceil(legendNum/2);
        var newLegend = [];
        var dataIndex = [];
        var colIndex = 0;
        for(var i=0; i<legendNum; i++){
            dataIndex.push(legendData[i]);
            if((legendNum > 11 && (i+1) % colMaxNum == 0) || (i+1) == legendNum){
                var legendObj = {
                    orient: 'vertical',
                    itemHeight: 8,
                    itemWidth: 8,
                    icon: "rect",
                    tooltip :{
                        show:true
                    },
                    textStyle: {
                        fontWeight : 'normal',
                        color: '#1C9AD7',
                        fontSize : fontSize
                    },
                    x:'right',
                    y: 'center',
                    align:'left',
                    left:(left+colIndex*12)+'%',
                    data: dataIndex,
                    formatter : function(data){
                        //maxLength参数为0时长度超过10省略号显示
                        if(maxLength == 0){
                            if(data.length > 10){
                                return data.substring(0,9)+'...';
                            }
                        //maxLength参数不为0时长度超过maxLength按单词换行
                        } else if (data.length > maxLength){
                            return newLineProcess(data,maxLength);
                        }
                        return data;
                    }
                };
                newLegend.push(legendObj);
                dataIndex = [];
                colIndex++;
            }
        }
        return newLegend;
    }
    //获取数组最大值
    function getArrayMaxValue(arr){
        var max = arr[0];
        for(var i=1; i<arr.length; i++){
            if(arr[i] >= max){
                max = arr[i];
            }
        }
        return max;
    }

    /**
     * base64加密对象
     * @constructs Base64Fuc 
     */
    function Base64Fuc() {
            _keyStr = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
            this.encode = function (input) {
                var output = "";
                var chr1, chr2, chr3, enc1, enc2, enc3, enc4;
                var i = 0;
                input = _utf8_encode(input);
                while (i < input.length) {
                    chr1 = input.charCodeAt(i++);
                    chr2 = input.charCodeAt(i++);
                    chr3 = input.charCodeAt(i++);
                    enc1 = chr1 >> 2;
                    enc2 = ((chr1 & 3) << 4) | (chr2 >> 4);
                    enc3 = ((chr2 & 15) << 2) | (chr3 >> 6);
                    enc4 = chr3 & 63;
                    if (isNaN(chr2)) {
                        enc3 = enc4 = 64;
                    } else if (isNaN(chr3)) {
                        enc4 = 64;
                    }
                    output = output +
                        _keyStr.charAt(enc1) + _keyStr.charAt(enc2) +
                        _keyStr.charAt(enc3) + _keyStr.charAt(enc4);
                }
                return output;
            }

            this.decode = function (input) {
                var output = "";
                var chr1, chr2, chr3;
                var enc1, enc2, enc3, enc4;
                var i = 0;
                input = input.replace(/[^A-Za-z0-9\+\/\=]/g, "");
                while (i < input.length) {
                    enc1 = _keyStr.indexOf(input.charAt(i++));
                    enc2 = _keyStr.indexOf(input.charAt(i++));
                    enc3 = _keyStr.indexOf(input.charAt(i++));
                    enc4 = _keyStr.indexOf(input.charAt(i++));
                    chr1 = (enc1 << 2) | (enc2 >> 4);
                    chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
                    chr3 = ((enc3 & 3) << 6) | enc4;
                    output = output + String.fromCharCode(chr1);
                    if (enc3 != 64) {
                        output = output + String.fromCharCode(chr2);
                    }
                    if (enc4 != 64) {
                        output = output + String.fromCharCode(chr3);
                    }
                }
                output = _utf8_decode(output);
                return output;
            }

            _utf8_encode = function (string) {
                string = string.replace(/\r\n/g, "\n");
                var utftext = "";
                for (var n = 0; n < string.length; n++) {
                    var c = string.charCodeAt(n);
                    if (c < 128) {
                        utftext += String.fromCharCode(c);
                    } else if ((c > 127) && (c < 2048)) {
                        utftext += String.fromCharCode((c >> 6) | 192);
                        utftext += String.fromCharCode((c & 63) | 128);
                    } else {
                        utftext += String.fromCharCode((c >> 12) | 224);
                        utftext += String.fromCharCode(((c >> 6) & 63) | 128);
                        utftext += String.fromCharCode((c & 63) | 128);
                    }

                }
                return utftext;
            }

            _utf8_decode = function (utftext) {
                var string = "";
                var i = 0;
                while (i < utftext.length) {
                    var c = utftext.charCodeAt(i);
                    if (c < 128) {
                        string += String.fromCharCode(c);
                        i++;
                    } else if ((c > 191) && (c < 224)) {
                        var c2 = utftext.charCodeAt(i + 1);
                        string += String.fromCharCode(((c & 31) << 6) | (c2 & 63));
                        i += 2;
                    } else {
                        var c2 = utftext.charCodeAt(i + 1);
                        var c3 = utftext.charCodeAt(i + 2);
                        string += String.fromCharCode(((c & 15) << 12) | ((c2 & 63) << 6) | (c3 & 63));
                        i += 3;
                    }
                }
                return string;
            }
        }
    /**
     * 将url最后一项替换为replacement
     * @param url {String} 被替换URL
     * @param replacement {String} 替换项
     * */
    function dropUrlLastReplace(url, replacement) {
        if (url){
            var arr = url.split("/");
            arr.pop();
            return arr.concat(replacement).join("/")
        }
        return "";
    }

    /**
     * 字符串固定位置插入字符
     * @param {string} source 
     * @param {number} start 
     * @param {string} newStr 
     */
    function stringInsertIndexIn(source,start,newStr){
        return source.slice(0,start) + newStr + source.slice(start);
    }

    /**
     * 数组 groupBy 函数
     * @param {object[]} arr 原数组
     * @param {Function} fun 回调函数
     */
    function groupBy(arr, fun){
        let groupResult = {}
        arr.forEach(function (obj) {
            let groupKey = JSON.stringify(fun(obj));
            groupResult[groupKey] = groupResult[groupKey] || [];
            groupResult[groupKey].push(obj)
        })
        return groupResult
    }

    return {
        destroyOrSave: destroyOrSave,
        desModule: desModule,
        transitionProperty: transitionProperty,
        transition: transition,
        catalogOrtable: catalogOrtable,
        appendKey: appendKey,
        appendData: appendData,
        transitionValue: transitionValue,
        getValue: getValue,
        deleteUndefined: deleteUndefined,
        filter: filter,
        copyType: copyType,
        deepCopy: deepCopy,
        getKeyToArr: getKeyToArr,
        getArrObjLabel: getArrObjLabel,
        getArrObjlabelsStr: getArrObjlabelsStr,
        appendArrIndex: appendArrIndex,
        appendArrChild: appendArrChild,
        appendKey1: appendKey1,
        appendKey2: appendKey2,
        appendKey3: appendKey3,
        deleteAllHollowModule: deleteAllHollowModule,
        initDelGraphPosition: initDelGraphPosition,
        getObjLableToArr: getObjLableToArr,
        deleteObjKey: deleteObjKey,
        deleteArrKeyObj: deleteArrKeyObj,
        arrMapToObj: arrMapToObj,
        getObjLabel: getObjLabel,
        deleteArrItem: deleteArrItem,
        getGraphData: getGraphData,
        setObjlength: setObjlength,
        setTableHeight: setTableHeight,
        generateID: generateID,
        _id:_id,
        _initHeight:_initHeight,
        getMonDay:getMonDay,
        copyArr:copyArr,
        copyObj:copyObj,
        getObjLenght:getObjLenght,
        check_other_char:check_other_char,
        getSplitBar:getSplitBar,
        uniquel:uniquel,
        getArrObjKeyEqualValue:getArrObjKeyEqualValue,
        clkShowPanel:clkShowPanel,
        timeFormat:timeFormat,
        isDateFormat:isDateFormat,
        getLegend:getLegend,
        newLineProcess:newLineProcess,
        getPieLegends:getPieLegends,
        getArrayMaxValue:getArrayMaxValue,
        Base64Fuc:Base64Fuc,
        dropUrlLastReplace:dropUrlLastReplace,
        stringInsertIndexIn:stringInsertIndexIn,
        groupBy:groupBy
    }
});