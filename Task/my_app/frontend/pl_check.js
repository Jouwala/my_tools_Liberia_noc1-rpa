import { createHotContext as __vite__createHotContext } from "/myapp/@vite/client";import.meta.hot = __vite__createHotContext("/src/pages/PacketLossDashboard.tsx");const useEffect = __vite__cjsImport0_react["useEffect"]; const useState = __vite__cjsImport0_react["useState"]; const useMemo = __vite__cjsImport0_react["useMemo"]; const useCallback = __vite__cjsImport0_react["useCallback"];const dayjs = __vite__cjsImport7_dayjs;const _jsxDEV = __vite__cjsImport11_react_jsxDevRuntime["jsxDEV"]; const _Fragment = __vite__cjsImport11_react_jsxDevRuntime["Fragment"];// Packet Loss Dashboard - 丢包看板（参考 RealTime Alarm Map 风格）
// 数据源: lte_pl.sqlite3（RAN UME SDR/IPRAN IPPD 丢包率，近7天小时粒度）
import __vite__cjsImport0_react from "/myapp/node_modules/.vite/deps/react.js?v=01bd9f66";
import { Card, Row, Col, Tag, Spin, Alert, Empty, Table, Input, Button, Switch, Popover } from "/myapp/node_modules/.vite/deps/antd.js?v=f602a26c";
import { AlertOutlined, WarningOutlined, EnvironmentOutlined, PieChartOutlined, BarChartOutlined, DashboardOutlined, DownloadOutlined, SearchOutlined, RightOutlined, ClockCircleOutlined, CheckCircleOutlined, DisconnectOutlined, CopyOutlined, InfoCircleOutlined, ApartmentOutlined } from "/myapp/node_modules/.vite/deps/@ant-design_icons.js?v=556a5094";
import ReactECharts from "/myapp/node_modules/.vite/deps/echarts-for-react.js?v=d5cf593e";
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline } from "/myapp/node_modules/.vite/deps/react-leaflet.js?v=65bff70b";
import "/myapp/node_modules/leaflet/dist/leaflet.css";
import * as XLSX from "/myapp/node_modules/.vite/deps/xlsx.js?v=c9ba823b";
import __vite__cjsImport7_dayjs from "/myapp/node_modules/.vite/deps/dayjs.js?v=5e98cc8a";
import api from "/myapp/src/api.ts";
import { cachedGet } from "/myapp/src/cache.ts";
import DraggableClickModal from "/myapp/src/components/DraggableClickModal.tsx";
var _jsxFileName = "d:/01_RPA/Task/my_app/frontend/src/pages/PacketLossDashboard.tsx";
import __vite__cjsImport11_react_jsxDevRuntime from "/myapp/node_modules/.vite/deps/react_jsx-dev-runtime.js?v=01bd9f66";
var _s = $RefreshSig$(), _s2 = $RefreshSig$(), _s3 = $RefreshSig$();
// ========== Warehouse 风格设计令牌（与 AlarmDashboard 一致） ==========
const WH = {
	bg: "linear-gradient(180deg, #0a1929 0%, #0d2138 100%)",
	cardBg: "linear-gradient(145deg, #141f33 0%, #112540 100%)",
	cardBorder: "1px solid rgba(100,255,218,0.18)",
	cardBorderHover: "1px solid rgba(100,255,218,0.55)",
	teal: "#64ffda",
	blue: "#4fc3f7",
	indigo: "#7986cb",
	text: "#e6f4ff",
	textMuted: "#94a3b8",
	textDim: "#64748b",
	accentGrad: "linear-gradient(135deg, #64ffda, #4fc3f7)"
};
const STATUS_ORDER = [
	"Critical[>5]",
	"Major[1-5]",
	"Minor[0.5-1]",
	"Warning[0.1-0.5]",
	"No Packet loss[<0.1]"
];
const STATUS_COLORS = {
	"Critical[>5]": "#ff4757",
	"Major[1-5]": "#ff922b",
	"Minor[0.5-1]": "#ffd43b",
	"Warning[0.1-0.5]": "#74c0fc",
	"No Packet loss[<0.1]": "#51cf66"
};
const STATUS_SHORT = {
	"Critical[>5]": "Critical",
	"Major[1-5]": "Major",
	"Minor[0.5-1]": "Minor",
	"Warning[0.1-0.5]": "Warning",
	"No Packet loss[<0.1]": "OK"
};
// 指标计算说明（鼠标悬停「?」查看，可复制）
const METRIC_EXPLAIN = {
	"Total Sites": "被纳入丢包监控的站点总数。\n" + "数据来源：Packet Loss Status Report 的站点主数据（lte_pl.sqlite3，近 7 天逐小时粒度）。",
	"Critical": "近 24 小时最大丢包率 > 5% 的站点数。\n" + "计算：取该站点最近 24 小时逐小时丢包率的最大值（Last 1 day Max PL），> 5% 判为 Critical。",
	"Major": "近 24 小时最大丢包率介于 1%–5%（含）的站点数。\n" + "计算：Last 1 day Max PL 落在 [1, 5] 区间判为 Major。",
	"Minor": "近 24 小时最大丢包率介于 0.5%–1%（含）的站点数。\n" + "计算：Last 1 day Max PL 落在 [0.5, 1] 区间判为 Minor。",
	"Warning": "近 24 小时最大丢包率介于 0.1%–0.5%（含）的站点数。\n" + "计算：Last 1 day Max PL 落在 [0.1, 0.5] 区间判为 Warning。",
	"No Packet loss": "近 24 小时最大丢包率 < 0.1% 的站点数（视为正常）。\n" + "计算：Last 1 day Max PL < 0.1% 判为 No Packet loss。",
	"Affected Sites": "近 7 天内出现过丢包（至少 1 个小时丢包率 > 0）的站点数。\n" + "与 Total Sites 区别：Total Sites 为纳入监控的站点总数；Affected Sites 仅统计实际发生丢包的站点。\n" + "数据来源：lte_pl.sqlite3 近 7 天逐小时丢包率。",
	"Data Granularity": "数据粒度：近 7 天逐小时（SDR + IPRAN 的 IPPD 丢包率）。\n" + "SDR = 软定义无线（3G/2G）；IPRAN = IP 化回传承载网。"
};
// 拓扑视图：按 backhaul/transport 类型（gateway 字段）聚合站点，
// 每个 gateway 计算质心作为「汇聚节点」，并把每个成员站点连到其最近的同网关邻居，
// 形成 hub-and-spoke 拓扑。以下为各 gateway 的配色。
const GW_COLORS = {
	"MW": "#36cfc9",
	"Satellite Link": "#ffc53d",
	"IPRAN": "#9254de",
	"Start Link": "#ff7a45"
};
const gwColor = (gw) => GW_COLORS[gw] || "#8c8c8c";
const darkTooltip = () => ({
	backgroundColor: "rgba(10,25,41,0.95)",
	borderColor: "rgba(100,255,218,0.25)",
	borderWidth: 1,
	textStyle: {
		color: "#e6f4ff",
		fontSize: 12
	},
	extraCssText: "box-shadow:0 4px 16px rgba(0,0,0,0.4);"
});
const axisLabel = () => ({
	color: "#94a3b8",
	fontSize: 11
});
const axisLine = () => ({ lineStyle: { color: "#22324d" } });
const splitLine = () => ({ lineStyle: {
	type: "dashed",
	color: "rgba(255,255,255,0.06)"
} });
const CHART_HEIGHT = 280;
const SectionTitle = ({ icon, title, sub }) => /* @__PURE__ */ _jsxDEV("div", {
	style: {
		display: "flex",
		alignItems: "center",
		gap: 10,
		margin: "22px 0 14px",
		padding: "0 0 10px",
		borderBottom: "1px solid rgba(100,255,218,0.18)"
	},
	children: [
		/* @__PURE__ */ _jsxDEV("span", {
			style: {
				width: 28,
				height: 28,
				borderRadius: 6,
				background: WH.accentGrad,
				display: "flex",
				alignItems: "center",
				justifyContent: "center",
				color: "#06222e",
				fontSize: 14
			},
			children: icon
		}, void 0, false, {
			fileName: _jsxFileName,
			lineNumber: 110,
			columnNumber: 5
		}, this),
		/* @__PURE__ */ _jsxDEV("span", {
			style: {
				fontSize: 16,
				fontWeight: 700,
				color: WH.text,
				letterSpacing: "-0.3px"
			},
			children: title
		}, void 0, false, {
			fileName: _jsxFileName,
			lineNumber: 116,
			columnNumber: 5
		}, this),
		sub && /* @__PURE__ */ _jsxDEV("span", {
			style: {
				fontSize: 12,
				color: WH.textDim,
				marginLeft: 4
			},
			children: sub
		}, void 0, false, {
			fileName: _jsxFileName,
			lineNumber: 117,
			columnNumber: 13
		}, this)
	]
}, void 0, true, {
	fileName: _jsxFileName,
	lineNumber: 105,
	columnNumber: 3
}, this);
_c = SectionTitle;
// 通用「计算说明」悬停气泡（带复制）。供指标卡以外的地方（如头部 Affected Sites 标签）复用
const MetricExplainPopover = ({ text, children }) => {
	_s();
	const [copied, setCopied] = useState(false);
	const copy = useCallback(async () => {
		try {
			if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
			else {
				const ta = document.createElement("textarea");
				ta.value = text;
				ta.style.position = "fixed";
				ta.style.opacity = "0";
				document.body.appendChild(ta);
				ta.select();
				document.execCommand("copy");
				document.body.removeChild(ta);
			}
			setCopied(true);
			setTimeout(() => setCopied(false), 1500);
		} catch {}
	}, [text]);
	if (!text) return /* @__PURE__ */ _jsxDEV(_Fragment, { children }, void 0, false, {
		fileName: _jsxFileName,
		lineNumber: 135,
		columnNumber: 21
	}, this);
	return /* @__PURE__ */ _jsxDEV(Popover, {
		trigger: "hover",
		placement: "bottom",
		mouseEnterDelay: .1,
		content: /* @__PURE__ */ _jsxDEV("div", {
			style: {
				maxWidth: 300,
				fontSize: 12,
				lineHeight: 1.7
			},
			children: [/* @__PURE__ */ _jsxDEV("div", {
				style: {
					color: WH.textMuted,
					whiteSpace: "pre-line"
				},
				children: text
			}, void 0, false, {
				fileName: _jsxFileName,
				lineNumber: 140,
				columnNumber: 11
			}, this), /* @__PURE__ */ _jsxDEV(Button, {
				size: "small",
				type: "link",
				icon: /* @__PURE__ */ _jsxDEV(CopyOutlined, {}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 141,
					columnNumber: 50
				}, this),
				onClick: copy,
				style: {
					paddingLeft: 0,
					marginTop: 8,
					height: "auto",
					color: WH.teal
				},
				children: copied ? "已复制 ✓" : "复制说明"
			}, void 0, false, {
				fileName: _jsxFileName,
				lineNumber: 141,
				columnNumber: 11
			}, this)]
		}, void 0, true, {
			fileName: _jsxFileName,
			lineNumber: 139,
			columnNumber: 9
		}, this),
		children
	}, void 0, false, {
		fileName: _jsxFileName,
		lineNumber: 137,
		columnNumber: 5
	}, this);
};
_s(MetricExplainPopover, "nK+5kxrGTytn1m9G9vwBQ76mZ74=");
_c2 = MetricExplainPopover;
const SummaryCard = ({ icon, value, label, color, onClick, explain }) => {
	_s2();
	const [copied, setCopied] = useState(false);
	const copyExplain = useCallback(async () => {
		if (!explain) return;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(explain);
			} else {
				const ta = document.createElement("textarea");
				ta.value = explain;
				ta.style.position = "fixed";
				ta.style.opacity = "0";
				document.body.appendChild(ta);
				ta.select();
				document.execCommand("copy");
				document.body.removeChild(ta);
			}
			setCopied(true);
			setTimeout(() => setCopied(false), 1500);
		} catch {}
	}, [explain]);
	return /* @__PURE__ */ _jsxDEV(Card, {
		size: "small",
		hoverable: true,
		onClick,
		style: {
			background: WH.cardBg,
			border: WH.cardBorder,
			borderRadius: 12,
			cursor: "pointer",
			transition: "all .2s",
			position: "relative",
			overflow: "hidden",
			boxShadow: "0 4px 16px rgba(0,0,0,0.25)"
		},
		onMouseEnter: (e) => {
			e.currentTarget.style.border = WH.cardBorderHover;
		},
		onMouseLeave: (e) => {
			e.currentTarget.style.border = WH.cardBorder;
		},
		children: [
			/* @__PURE__ */ _jsxDEV("div", { style: {
				position: "absolute",
				left: 0,
				top: 0,
				bottom: 0,
				width: 4,
				background: color,
				opacity: .9
			} }, void 0, false, {
				fileName: _jsxFileName,
				lineNumber: 185,
				columnNumber: 7
			}, this),
			explain && /* @__PURE__ */ _jsxDEV(Popover, {
				trigger: "hover",
				placement: "top",
				mouseEnterDelay: .1,
				content: /* @__PURE__ */ _jsxDEV("div", {
					style: {
						maxWidth: 280,
						fontSize: 12,
						lineHeight: 1.7
					},
					children: [
						/* @__PURE__ */ _jsxDEV("div", {
							style: {
								fontWeight: 700,
								color: WH.teal,
								marginBottom: 6
							},
							children: [label, " · 计算说明"]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 193,
							columnNumber: 15
						}, this),
						/* @__PURE__ */ _jsxDEV("div", {
							style: {
								color: WH.textMuted,
								whiteSpace: "pre-line"
							},
							children: explain
						}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 194,
							columnNumber: 15
						}, this),
						/* @__PURE__ */ _jsxDEV(Button, {
							size: "small",
							type: "link",
							icon: /* @__PURE__ */ _jsxDEV(CopyOutlined, {}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 195,
								columnNumber: 54
							}, this),
							onClick: copyExplain,
							style: {
								paddingLeft: 0,
								marginTop: 8,
								height: "auto",
								color: WH.teal
							},
							children: copied ? "已复制 ✓" : "复制说明"
						}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 195,
							columnNumber: 15
						}, this)
					]
				}, void 0, true, {
					fileName: _jsxFileName,
					lineNumber: 192,
					columnNumber: 13
				}, this),
				children: /* @__PURE__ */ _jsxDEV("span", {
					onClick: (e) => e.stopPropagation(),
					style: {
						position: "absolute",
						top: 6,
						right: 8,
						zIndex: 2,
						cursor: "help",
						color: WH.textDim,
						fontSize: 13
					},
					children: /* @__PURE__ */ _jsxDEV(InfoCircleOutlined, {}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 206,
						columnNumber: 13
					}, this)
				}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 202,
					columnNumber: 11
				}, this)
			}, void 0, false, {
				fileName: _jsxFileName,
				lineNumber: 187,
				columnNumber: 9
			}, this),
			/* @__PURE__ */ _jsxDEV("div", {
				style: {
					display: "flex",
					justifyContent: "space-between",
					alignItems: "center"
				},
				children: [/* @__PURE__ */ _jsxDEV("div", { children: [/* @__PURE__ */ _jsxDEV("div", {
					style: {
						fontSize: 30,
						fontWeight: 800,
						color,
						lineHeight: 1.2,
						textShadow: `0 0 14px ${color}55`
					},
					children: value
				}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 212,
					columnNumber: 11
				}, this), /* @__PURE__ */ _jsxDEV("div", {
					style: {
						fontSize: 12,
						color: WH.textMuted,
						marginTop: 4,
						fontWeight: 500
					},
					children: label
				}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 213,
					columnNumber: 11
				}, this)] }, void 0, true, {
					fileName: _jsxFileName,
					lineNumber: 211,
					columnNumber: 9
				}, this), /* @__PURE__ */ _jsxDEV("span", {
					style: {
						fontSize: 38,
						opacity: .16,
						color
					},
					children: icon
				}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 215,
					columnNumber: 9
				}, this)]
			}, void 0, true, {
				fileName: _jsxFileName,
				lineNumber: 210,
				columnNumber: 7
			}, this),
			/* @__PURE__ */ _jsxDEV("div", {
				style: {
					textAlign: "right",
					fontSize: 10,
					color: WH.teal,
					fontWeight: 600,
					marginTop: 2,
					display: "flex",
					alignItems: "center",
					justifyContent: "flex-end",
					gap: 2
				},
				children: ["点击下钻 ", /* @__PURE__ */ _jsxDEV(RightOutlined, { style: { fontSize: 9 } }, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 218,
					columnNumber: 14
				}, this)]
			}, void 0, true, {
				fileName: _jsxFileName,
				lineNumber: 217,
				columnNumber: 7
			}, this)
		]
	}, void 0, true, {
		fileName: _jsxFileName,
		lineNumber: 177,
		columnNumber: 5
	}, this);
};
_s2(SummaryCard, "/bfR9PHspScVoPc9p/gnuuNNCJI=");
_c3 = SummaryCard;
const strSorter = (a, b, key) => String(a[key] ?? "").localeCompare(String(b[key] ?? ""));
const getUniqueFilters = (data, key) => {
	const vals = new Set();
	data.forEach((r) => {
		if (r[key] != null && r[key] !== "") vals.add(String(r[key]));
	});
	return Array.from(vals).map((v) => ({
		text: v,
		value: v
	}));
};
export default function PacketLossDashboard() {
	_s3();
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState(null);
	const [data, setData] = useState(null);
	const [mapSites, setMapSites] = useState([]);
	const [includeOk, setIncludeOk] = useState(false);
	const [hiddenStatuses, setHiddenStatuses] = useState(new Set());
	// 拓扑显示开关：开启后复用 GIS Map 的真实拓扑链路（/api/gis/topology），按传输类型着色
	const [showTopology, setShowTopology] = useState(false);
	const [gisTopology, setGisTopology] = useState([]);
	useEffect(() => {
		if (showTopology && gisTopology.length === 0) {
			api.get("/gis/topology").then((res) => setGisTopology(res.data.links || [])).catch(() => {});
		}
	}, [showTopology]);
	const toggleStatusVisible = useCallback((st) => {
		setHiddenStatuses((prev) => {
			const next = new Set(prev);
			if (next.has(st)) next.delete(st);
			else next.add(st);
			return next;
		});
	}, []);
	// 下钻
	const [drillOpen, setDrillOpen] = useState(false);
	const [drillLoading, setDrillLoading] = useState(false);
	const [drillData, setDrillData] = useState([]);
	const [drillTitle, setDrillTitle] = useState("");
	const [drillSearch, setDrillSearch] = useState("");
	const [drillTotal, setDrillTotal] = useState(0);
	const [drillAnchor, setDrillAnchor] = useState(null);
	useEffect(() => {
		setLoading(true);
		setError(null);
		Promise.all([cachedGet("pl:overview", () => api.get("/packet-loss-dashboard/overview")), cachedGet(`pl:map:${includeOk}`, () => api.get("/packet-loss-dashboard/map-sites", { params: { include_ok: includeOk } }))]).then(([ov, mp]) => {
			setData(ov.data);
			setMapSites(mp.data.sites || []);
			setError(null);
		}).catch((err) => {
			console.error("Packet Loss API error:", err);
			setError(err.message || "Failed to load");
		}).finally(() => setLoading(false));
	}, [includeOk]);
	const openDrilldown = useCallback((trigger, status, title) => {
		let anchor = null;
		if (trigger && typeof trigger.clientX === "number") {
			anchor = {
				x: trigger.clientX,
				y: trigger.clientY
			};
		} else if (trigger?.event?.event && typeof trigger.event.event.clientX === "number") {
			anchor = {
				x: trigger.event.event.clientX,
				y: trigger.event.event.clientY
			};
		}
		setDrillAnchor(anchor);
		setDrillOpen(true);
		setDrillLoading(true);
		setDrillData([]);
		setDrillSearch("");
		setDrillTitle(title);
		api.get("/packet-loss-dashboard/drilldown", { params: {
			status,
			limit: 800
		} }).then((res) => {
			setDrillData(res.data.data || []);
			setDrillTotal(res.data.total || 0);
		}).catch(() => setDrillTitle("Failed to load data")).finally(() => setDrillLoading(false));
	}, []);
	const filteredDrillData = useMemo(() => {
		if (!drillSearch.trim()) return drillData;
		const lower = drillSearch.toLowerCase();
		return drillData.filter((row) => Object.values(row).some((v) => v != null && String(v).toLowerCase().includes(lower)));
	}, [drillData, drillSearch]);
	const exportToExcel = useCallback(() => {
		if (!filteredDrillData.length) return;
		const keys = Object.keys(filteredDrillData[0]);
		const rows = filteredDrillData.map((row) => keys.map((k) => row[k] == null ? "" : String(row[k])));
		const ws = XLSX.utils.aoa_to_sheet([keys, ...rows]);
		ws["!cols"] = keys.map(() => ({ wch: 18 }));
		const wb = XLSX.utils.book_new();
		const fname = `PacketLoss_${dayjs().format("YYYYMMDD_HHmmss")}`;
		XLSX.utils.book_append_sheet(wb, ws, fname.substring(0, 31));
		XLSX.writeFile(wb, `${fname}.xlsx`);
	}, [filteredDrillData]);
	const drillColumns = useMemo(() => {
		if (!drillData.length) return [];
		return Object.keys(drillData[0]).map((k) => ({
			title: k.replace(/_/g, " "),
			dataIndex: k,
			key: k,
			width: 130,
			ellipsis: true,
			sorter: (a, b) => strSorter(a, b, k),
			filters: getUniqueFilters(drillData, k),
			onFilter: (v, r) => String(r[k]) === v
		}));
	}, [drillData]);
	// ========== 图表配置 ==========
	const statusPieOption = useMemo(() => {
		if (!data?.status_pie) return {};
		return {
			tooltip: {
				...darkTooltip(),
				trigger: "item",
				formatter: "{b}<br/>{c} sites ({d}%)"
			},
			legend: {
				orient: "vertical",
				right: 0,
				top: "center",
				textStyle: {
					fontSize: 10,
					color: WH.textMuted
				},
				itemWidth: 10,
				itemHeight: 10
			},
			series: [{
				type: "pie",
				radius: ["38%", "65%"],
				center: ["38%", "50%"],
				data: data.status_pie.map((s) => ({
					name: s.status,
					value: s.count,
					itemStyle: { color: STATUS_COLORS[s.status] || WH.teal }
				})),
				label: {
					fontSize: 10,
					color: WH.text,
					formatter: "{c}"
				},
				emphasis: { itemStyle: {
					shadowBlur: 10,
					shadowColor: "rgba(100,255,218,0.4)"
				} }
			}]
		};
	}, [data]);
	const regionOption = useMemo(() => {
		if (!data?.region_dist) return {};
		const entries = Object.entries(data.region_dist);
		if (!entries.length) return {};
		return {
			tooltip: {
				...darkTooltip(),
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (ps) => {
					const idx = ps[0].dataIndex;
					const b = entries[idx][1];
					return `<div style="font-weight:600;margin-bottom:4px">${entries[idx][0]}</div>` + `Affected Sites: <strong>${b.sites}</strong><br/>Critical: <strong>${b.critical}</strong><br/>Max PL: <strong>${b.max_pl.toFixed(2)}%</strong>`;
				}
			},
			grid: {
				left: 40,
				right: 20,
				top: 10,
				bottom: 40
			},
			xAxis: {
				type: "category",
				data: entries.map(([k]) => k),
				axisLabel: {
					...axisLabel(),
					rotate: 30
				},
				axisLine: axisLine()
			},
			yAxis: {
				type: "value",
				splitLine: splitLine(),
				axisLabel: axisLabel()
			},
			series: [{
				type: "bar",
				barMaxWidth: 28,
				data: entries.map(([, b], i) => ({
					value: b.sites,
					itemStyle: {
						color: {
							type: "linear",
							x: 0,
							y: 0,
							x2: 0,
							y2: 1,
							colorStops: [{
								offset: 0,
								color: i === 0 ? "#ff4757" : "#64ffda"
							}, {
								offset: 1,
								color: "#0d2138"
							}]
						},
						borderRadius: [
							4,
							4,
							0,
							0
						]
					}
				})),
				label: {
					show: true,
					position: "top",
					fontSize: 10,
					color: WH.textMuted,
					fontWeight: 600
				}
			}]
		};
	}, [data]);
	const trendOption = useMemo(() => {
		if (!data?.daily_trend?.length) return {};
		const days = data.daily_trend.map((d) => d.day.slice(5));
		return {
			tooltip: {
				...darkTooltip(),
				trigger: "axis"
			},
			legend: {
				data: ["Median PL (%)", "Affected Sites"],
				bottom: 0,
				textStyle: {
					fontSize: 11,
					color: WH.textMuted
				}
			},
			grid: {
				left: 50,
				right: 50,
				top: 20,
				bottom: 50
			},
			xAxis: {
				type: "category",
				data: days,
				axisLabel: axisLabel(),
				axisLine: axisLine()
			},
			yAxis: [{
				type: "value",
				name: "PL %",
				splitLine: splitLine(),
				axisLabel: axisLabel()
			}, {
				type: "value",
				name: "Sites",
				splitLine: { show: false },
				axisLabel: axisLabel()
			}],
			series: [{
				name: "Median PL (%)",
				type: "bar",
				barMaxWidth: 22,
				data: data.daily_trend.map((d) => d.median_pl),
				itemStyle: {
					color: {
						type: "linear",
						x: 0,
						y: 0,
						x2: 0,
						y2: 1,
						colorStops: [{
							offset: 0,
							color: "#64ffda"
						}, {
							offset: 1,
							color: "#4fc3f7"
						}]
					},
					borderRadius: [
						4,
						4,
						0,
						0
					]
				},
				label: {
					show: true,
					position: "top",
					fontSize: 10,
					color: WH.textMuted,
					formatter: (p) => `${p.value}%`
				}
			}, {
				name: "Affected Sites",
				type: "line",
				yAxisIndex: 1,
				smooth: true,
				data: data.daily_trend.map((d) => d.affected_sites),
				lineStyle: {
					color: "#ff922b",
					width: 2
				},
				itemStyle: { color: "#ff922b" },
				symbolSize: 6
			}]
		};
	}, [data]);
	const topSitesOption = useMemo(() => {
		if (!data?.top_sites?.length) return {};
		const sites = data.top_sites.slice(0, 12).reverse();
		return {
			tooltip: {
				...darkTooltip(),
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (ps) => {
					const idx = ps[0].dataIndex;
					const s = sites[idx];
					return `<div style="font-weight:600;margin-bottom:4px">${s.site_name}</div>` + `Status: <strong>${STATUS_SHORT[s.status] || s.status}</strong><br/>` + `Last-1-day Median PL: <strong>${s.last_day_median_pl}%</strong><br/>` + `Last-1-day Max PL: ${s.last_day_max_pl}%<br/>` + `Affected Hours: <strong>${s.affected_hours}</strong><br/>Region: ${s.region || "-"}`;
				}
			},
			grid: {
				left: 20,
				right: 60,
				top: 10,
				bottom: 10
			},
			xAxis: {
				type: "value",
				splitLine: splitLine(),
				axisLabel: axisLabel()
			},
			yAxis: {
				type: "category",
				data: sites.map((s) => s.site_name.length > 18 ? s.site_name.slice(0, 16) + ".." : s.site_name),
				axisLabel: {
					...axisLabel(),
					color: WH.text
				},
				axisLine: axisLine()
			},
			series: [{
				type: "bar",
				barMaxWidth: 16,
				data: sites.map((s) => ({
					value: s.last_day_median_pl,
					itemStyle: {
						color: STATUS_COLORS[s.status] || WH.teal,
						borderRadius: [
							0,
							4,
							4,
							0
						]
					}
				})),
				label: {
					show: true,
					position: "right",
					fontSize: 10,
					color: WH.textMuted,
					formatter: (p) => `${p.value}%`
				}
			}]
		};
	}, [data]);
	// 图例过滤：隐藏选中的状态 → 地图上不渲染对应站点
	// 必须放在 early-return 之前，保证 hook 调用顺序在每次渲染都一致（否则会改变 hook 数量 → 组件崩溃）
	const visibleSites = useMemo(() => mapSites.filter((s) => !hiddenStatuses.has(s.status)), [mapSites, hiddenStatuses]);
	// 拓扑：复用 GIS Map 的真实链路（/api/gis/topology），按传输类型（gateway）着色。
	// 用「可见站点的坐标 → gateway」就近匹配链路两端，判定该链路属于哪种传输类型并取色。
	// 仅绘制至少一端落在当前可见 PL 站点内的链路（随图例显隐联动）。放在 early-return 前，保持 hook 顺序稳定。
	const topology = useMemo(() => {
		const pts = [];
		for (const s of visibleSites) {
			if (s.lat != null && s.lng != null) pts.push({
				lat: s.lat,
				lng: s.lng,
				gw: s.gateway || ""
			});
		}
		const TH = .006;
		const matchGw = (lat, lng) => {
			let best = "";
			let bd = TH * TH;
			for (const p of pts) {
				const d = (p.lat - lat) ** 2 + (p.lng - lng) ** 2;
				if (d < bd) {
					bd = d;
					best = p.gw;
				}
			}
			return best;
		};
		const edges = [];
		const gwSeen = new Set();
		for (const l of gisTopology) {
			const gw = matchGw(l.lat_a, l.lng_a) || matchGw(l.lat_b, l.lng_b);
			if (!gw) continue;
			gwSeen.add(gw);
			edges.push({
				positions: [[l.lat_a, l.lng_a], [l.lat_b, l.lng_b]],
				color: gwColor(gw),
				isHub: !!l.is_hub_link
			});
		}
		return {
			edges,
			gateways: [...gwSeen]
		};
	}, [visibleSites, gisTopology]);
	// ========== 渲染 ==========
	if (loading) return /* @__PURE__ */ _jsxDEV("div", {
		style: {
			background: WH.bg,
			borderRadius: 12,
			textAlign: "center",
			padding: 60
		},
		children: [/* @__PURE__ */ _jsxDEV(Spin, { size: "large" }, void 0, false, {
			fileName: _jsxFileName,
			lineNumber: 496,
			columnNumber: 7
		}, this), /* @__PURE__ */ _jsxDEV("div", {
			style: {
				marginTop: 12,
				color: WH.textMuted
			},
			children: "Loading Packet Loss Dashboard..."
		}, void 0, false, {
			fileName: _jsxFileName,
			lineNumber: 497,
			columnNumber: 7
		}, this)]
	}, void 0, true, {
		fileName: _jsxFileName,
		lineNumber: 495,
		columnNumber: 5
	}, this);
	if (error) return /* @__PURE__ */ _jsxDEV(Alert, {
		type: "error",
		message: "Failed to load Packet Loss Dashboard",
		description: error,
		showIcon: true,
		style: { margin: 16 }
	}, void 0, false, {
		fileName: _jsxFileName,
		lineNumber: 500,
		columnNumber: 21
	}, this);
	if (!data) return /* @__PURE__ */ _jsxDEV(Empty, { description: "No packet loss data available (run task: packet_loss_sync)" }, void 0, false, {
		fileName: _jsxFileName,
		lineNumber: 501,
		columnNumber: 21
	}, this);
	const sc = data.status_counts || {};
	const fmt = (n) => (n ?? 0).toLocaleString();
	const pageWrap = {
		background: WH.bg,
		borderRadius: 12,
		padding: 4,
		minHeight: "calc(100vh - 110px)"
	};
	const cardWrap = {
		background: WH.cardBg,
		border: WH.cardBorder,
		borderRadius: 12,
		boxShadow: "0 4px 16px rgba(0,0,0,0.25)"
	};
	const chartClick = (titlePrefix) => (p) => openDrilldown(p, p.name, `${titlePrefix} = ${STATUS_SHORT[p.name] || p.name}`);
	return /* @__PURE__ */ _jsxDEV("div", {
		style: {
			...pageWrap,
			display: "flex",
			flexDirection: "row",
			gap: 12,
			alignItems: "flex-start"
		},
		children: [
			/* @__PURE__ */ _jsxDEV("div", {
				style: {
					flex: "1 1 0",
					minWidth: 0,
					display: "flex",
					flexDirection: "column",
					gap: 4
				},
				children: [
					/* @__PURE__ */ _jsxDEV(Card, {
						size: "small",
						style: {
							background: "linear-gradient(135deg, #101a2e 0%, #112540 100%)",
							borderLeft: "4px solid #ff4757",
							borderRadius: 12,
							boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
							marginBottom: 4
						},
						children: /* @__PURE__ */ _jsxDEV("div", {
							style: {
								display: "flex",
								alignItems: "center",
								justifyContent: "space-between",
								flexWrap: "wrap",
								gap: 8
							},
							children: [/* @__PURE__ */ _jsxDEV("div", {
								style: {
									display: "flex",
									alignItems: "center",
									gap: 10
								},
								children: [
									/* @__PURE__ */ _jsxDEV(DisconnectOutlined, { style: {
										fontSize: 22,
										color: WH.teal
									} }, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 521,
										columnNumber: 13
									}, this),
									/* @__PURE__ */ _jsxDEV("span", {
										style: {
											fontSize: 15,
											fontWeight: 700,
											color: WH.text
										},
										children: "Packet Loss Status"
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 522,
										columnNumber: 13
									}, this),
									/* @__PURE__ */ _jsxDEV(MetricExplainPopover, {
										text: METRIC_EXPLAIN["Affected Sites"],
										children: /* @__PURE__ */ _jsxDEV(Tag, {
											color: "error",
											style: {
												borderRadius: 12,
												fontWeight: 600,
												cursor: "pointer"
											},
											onClick: (e) => openDrilldown(e, "all", "Sites with Packet Loss"),
											children: [fmt(data.affected_sites), " Affected Sites"]
										}, void 0, true, {
											fileName: _jsxFileName,
											lineNumber: 524,
											columnNumber: 15
										}, this)
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 523,
										columnNumber: 13
									}, this),
									/* @__PURE__ */ _jsxDEV(MetricExplainPopover, {
										text: METRIC_EXPLAIN["Data Granularity"],
										children: /* @__PURE__ */ _jsxDEV(Tag, {
											color: "cyan",
											style: {
												borderRadius: 12,
												fontWeight: 600
											},
											children: "7-Day Hourly · SDR + IPRAN"
										}, void 0, false, {
											fileName: _jsxFileName,
											lineNumber: 530,
											columnNumber: 15
										}, this)
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 529,
										columnNumber: 13
									}, this)
								]
							}, void 0, true, {
								fileName: _jsxFileName,
								lineNumber: 520,
								columnNumber: 11
							}, this), /* @__PURE__ */ _jsxDEV("div", {
								style: {
									display: "flex",
									alignItems: "center",
									gap: 12,
									fontSize: 12,
									color: WH.textDim
								},
								children: [/* @__PURE__ */ _jsxDEV(ClockCircleOutlined, {}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 534,
									columnNumber: 13
								}, this), /* @__PURE__ */ _jsxDEV("span", { children: ["Updated: ", data.generated_at ? String(data.generated_at).replace("T", " ").slice(0, 19) : "N/A"] }, void 0, true, {
									fileName: _jsxFileName,
									lineNumber: 535,
									columnNumber: 13
								}, this)]
							}, void 0, true, {
								fileName: _jsxFileName,
								lineNumber: 533,
								columnNumber: 11
							}, this)]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 519,
							columnNumber: 9
						}, this)
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 514,
						columnNumber: 7
					}, this),
					/* @__PURE__ */ _jsxDEV(Row, {
						gutter: [12, 12],
						children: [
							/* @__PURE__ */ _jsxDEV(Col, {
								span: 4,
								children: /* @__PURE__ */ _jsxDEV(SummaryCard, {
									icon: /* @__PURE__ */ _jsxDEV(EnvironmentOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 543,
										columnNumber: 30
									}, this),
									value: fmt(data.total_sites),
									label: "Total Sites",
									color: WH.teal,
									explain: METRIC_EXPLAIN["Total Sites"],
									onClick: () => openDrilldown(null, "all", "All Sites")
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 543,
									columnNumber: 11
								}, this)
							}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 542,
								columnNumber: 9
							}, this),
							STATUS_ORDER.filter((s) => s !== "No Packet loss[<0.1]").map((st) => /* @__PURE__ */ _jsxDEV(Col, {
								span: 4,
								children: /* @__PURE__ */ _jsxDEV(SummaryCard, {
									icon: st === "Critical[>5]" ? /* @__PURE__ */ _jsxDEV(AlertOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 550,
										columnNumber: 45
									}, this) : st === "Major[1-5]" ? /* @__PURE__ */ _jsxDEV(WarningOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 550,
										columnNumber: 87
									}, this) : /* @__PURE__ */ _jsxDEV(DashboardOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 550,
										columnNumber: 109
									}, this),
									value: fmt(sc[st] || 0),
									label: STATUS_SHORT[st],
									color: STATUS_COLORS[st],
									explain: METRIC_EXPLAIN[STATUS_SHORT[st]],
									onClick: () => openDrilldown(null, st, st)
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 549,
									columnNumber: 13
								}, this)
							}, st, false, {
								fileName: _jsxFileName,
								lineNumber: 548,
								columnNumber: 11
							}, this)),
							/* @__PURE__ */ _jsxDEV(Col, {
								span: 4,
								children: /* @__PURE__ */ _jsxDEV(SummaryCard, {
									icon: /* @__PURE__ */ _jsxDEV(CheckCircleOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 557,
										columnNumber: 30
									}, this),
									value: fmt(sc["No Packet loss[<0.1]"] || 0),
									label: "No Packet loss",
									color: STATUS_COLORS["No Packet loss[<0.1]"],
									explain: METRIC_EXPLAIN["No Packet loss"],
									onClick: () => openDrilldown(null, "No Packet loss[<0.1]", "No Packet loss[<0.1]")
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 557,
									columnNumber: 11
								}, this)
							}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 556,
								columnNumber: 9
							}, this)
						]
					}, void 0, true, {
						fileName: _jsxFileName,
						lineNumber: 541,
						columnNumber: 7
					}, this),
					/* @__PURE__ */ _jsxDEV(SectionTitle, {
						icon: /* @__PURE__ */ _jsxDEV(BarChartOutlined, {}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 564,
							columnNumber: 27
						}, this),
						title: "Loss Distribution",
						sub: "status · daily trend · region (click to drill down)"
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 564,
						columnNumber: 7
					}, this),
					/* @__PURE__ */ _jsxDEV(Row, {
						gutter: [12, 12],
						children: [
							/* @__PURE__ */ _jsxDEV(Col, {
								span: 7,
								children: /* @__PURE__ */ _jsxDEV(Card, {
									size: "small",
									title: /* @__PURE__ */ _jsxDEV("span", {
										style: {
											fontSize: 13,
											fontWeight: 600,
											color: WH.text
										},
										children: "Status Distribution"
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 567,
										columnNumber: 37
									}, this),
									style: cardWrap,
									children: /* @__PURE__ */ _jsxDEV(ReactECharts, {
										option: statusPieOption,
										style: { height: CHART_HEIGHT },
										onEvents: { click: chartClick("Status") }
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 568,
										columnNumber: 13
									}, this)
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 567,
									columnNumber: 11
								}, this)
							}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 566,
								columnNumber: 9
							}, this),
							/* @__PURE__ */ _jsxDEV(Col, {
								span: 10,
								children: /* @__PURE__ */ _jsxDEV(Card, {
									size: "small",
									title: /* @__PURE__ */ _jsxDEV("span", {
										style: {
											fontSize: 13,
											fontWeight: 600,
											color: WH.text
										},
										children: "Daily Trend (Last 7 Days)"
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 572,
										columnNumber: 37
									}, this),
									style: cardWrap,
									children: /* @__PURE__ */ _jsxDEV(ReactECharts, {
										option: trendOption,
										style: { height: CHART_HEIGHT }
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 573,
										columnNumber: 13
									}, this)
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 572,
									columnNumber: 11
								}, this)
							}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 571,
								columnNumber: 9
							}, this),
							/* @__PURE__ */ _jsxDEV(Col, {
								span: 7,
								children: /* @__PURE__ */ _jsxDEV(Card, {
									size: "small",
									title: /* @__PURE__ */ _jsxDEV("span", {
										style: {
											fontSize: 13,
											fontWeight: 600,
											color: WH.text
										},
										children: "Affected Sites by Region"
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 577,
										columnNumber: 37
									}, this),
									style: cardWrap,
									children: /* @__PURE__ */ _jsxDEV(ReactECharts, {
										option: regionOption,
										style: { height: CHART_HEIGHT }
									}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 578,
										columnNumber: 13
									}, this)
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 577,
									columnNumber: 11
								}, this)
							}, void 0, false, {
								fileName: _jsxFileName,
								lineNumber: 576,
								columnNumber: 9
							}, this)
						]
					}, void 0, true, {
						fileName: _jsxFileName,
						lineNumber: 565,
						columnNumber: 7
					}, this),
					/* @__PURE__ */ _jsxDEV(SectionTitle, {
						icon: /* @__PURE__ */ _jsxDEV(PieChartOutlined, {}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 584,
							columnNumber: 27
						}, this),
						title: "Top Sites",
						sub: "worst sites by last-1-day median PL"
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 584,
						columnNumber: 7
					}, this),
					/* @__PURE__ */ _jsxDEV(Card, {
						size: "small",
						title: /* @__PURE__ */ _jsxDEV("span", {
							style: {
								fontSize: 13,
								fontWeight: 600,
								color: WH.text
							},
							children: "Top Sites (Last-1-day Median PL)"
						}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 585,
							columnNumber: 33
						}, this),
						style: cardWrap,
						children: /* @__PURE__ */ _jsxDEV(ReactECharts, {
							option: topSitesOption,
							style: { height: 520 }
						}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 586,
							columnNumber: 9
						}, this)
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 585,
						columnNumber: 7
					}, this)
				]
			}, void 0, true, {
				fileName: _jsxFileName,
				lineNumber: 512,
				columnNumber: 7
			}, this),
			/* @__PURE__ */ _jsxDEV("div", {
				style: {
					flex: "0 0 33.333%",
					width: "33.333%",
					position: "sticky",
					top: 12,
					alignSelf: "flex-start"
				},
				children: /* @__PURE__ */ _jsxDEV(Card, {
					size: "small",
					style: {
						...cardWrap,
						marginBottom: 0
					},
					title: /* @__PURE__ */ _jsxDEV("div", {
						style: {
							display: "flex",
							alignItems: "center",
							justifyContent: "space-between"
						},
						children: [/* @__PURE__ */ _jsxDEV("span", {
							style: {
								fontSize: 13,
								fontWeight: 600,
								color: WH.text
							},
							children: [
								"Packet Loss Map (",
								mapSites.length,
								" sites)"
							]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 594,
							columnNumber: 13
						}, this), /* @__PURE__ */ _jsxDEV("span", {
							style: {
								fontSize: 11,
								color: WH.textMuted,
								display: "flex",
								alignItems: "center",
								gap: 8
							},
							children: [
								/* @__PURE__ */ _jsxDEV(Button, {
									size: "small",
									type: showTopology ? "primary" : "default",
									icon: /* @__PURE__ */ _jsxDEV(ApartmentOutlined, {}, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 597,
										columnNumber: 23
									}, this),
									onClick: () => setShowTopology((v) => !v),
									style: {
										height: 22,
										fontSize: 11,
										display: "inline-flex",
										alignItems: "center",
										gap: 4
									},
									children: "拓扑显示"
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 596,
									columnNumber: 15
								}, this),
								"Show OK sites ",
								/* @__PURE__ */ _jsxDEV(Switch, {
									size: "small",
									checked: includeOk,
									onChange: setIncludeOk
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 601,
									columnNumber: 29
								}, this)
							]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 595,
							columnNumber: 13
						}, this)]
					}, void 0, true, {
						fileName: _jsxFileName,
						lineNumber: 593,
						columnNumber: 11
					}, this),
					children: [
						/* @__PURE__ */ _jsxDEV(MapContainer, {
							center: [6.4, -9.4],
							zoom: 8,
							style: {
								height: "calc(100vh - 180px)",
								minHeight: 420,
								width: "100%",
								background: "#0a1929",
								borderRadius: 8
							},
							scrollWheelZoom: true,
							children: [
								/* @__PURE__ */ _jsxDEV(TileLayer, {
									attribution: "© <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
									url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 606,
									columnNumber: 13
								}, this),
								showTopology && topology.edges.map((e, i) => /* @__PURE__ */ _jsxDEV(Polyline, {
									positions: e.positions,
									pathOptions: {
										color: "#ffffff",
										weight: e.isHub ? 5 : 3,
										opacity: .3,
										interactive: false
									}
								}, `topo-c-${i}`, false, {
									fileName: _jsxFileName,
									lineNumber: 610,
									columnNumber: 15
								}, this)),
								showTopology && topology.edges.map((e, i) => /* @__PURE__ */ _jsxDEV(Polyline, {
									positions: e.positions,
									pathOptions: {
										color: e.color,
										weight: e.isHub ? 3 : 1.8,
										opacity: .9,
										interactive: false
									}
								}, `topo-${i}`, false, {
									fileName: _jsxFileName,
									lineNumber: 614,
									columnNumber: 15
								}, this)),
								visibleSites.map((s) => /* @__PURE__ */ _jsxDEV(CircleMarker, {
									center: [s.lat, s.lng],
									radius: Math.min(12, 5 + Math.log1p(s.last_day_max_pl) * 2),
									fillColor: STATUS_COLORS[s.status] || WH.teal,
									color: "#fff",
									weight: 1,
									fillOpacity: .85,
									children: /* @__PURE__ */ _jsxDEV(Popup, { children: /* @__PURE__ */ _jsxDEV("div", {
										style: {
											fontSize: 12,
											lineHeight: 1.6
										},
										children: [
											/* @__PURE__ */ _jsxDEV("strong", { children: s.site_name }, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 623,
												columnNumber: 21
											}, this),
											" ",
											s.site_code && `(${s.site_code})`,
											/* @__PURE__ */ _jsxDEV("br", {}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 623,
												columnNumber: 87
											}, this),
											"Status: ",
											/* @__PURE__ */ _jsxDEV("strong", {
												style: { color: STATUS_COLORS[s.status] },
												children: STATUS_SHORT[s.status] || s.status
											}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 624,
												columnNumber: 29
											}, this),
											/* @__PURE__ */ _jsxDEV("br", {}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 624,
												columnNumber: 125
											}, this),
											"Last-1-day Max PL: ",
											/* @__PURE__ */ _jsxDEV("strong", { children: [s.last_day_max_pl, "%"] }, void 0, true, {
												fileName: _jsxFileName,
												lineNumber: 625,
												columnNumber: 40
											}, this),
											/* @__PURE__ */ _jsxDEV("br", {}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 625,
												columnNumber: 77
											}, this),
											"7d Total PL: ",
											s.total_pl,
											"% · Affected Hours: ",
											s.affected_hours,
											/* @__PURE__ */ _jsxDEV("br", {}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 626,
												columnNumber: 84
											}, this),
											"Region: ",
											s.region || "-",
											" / ",
											s.province_county || "-",
											/* @__PURE__ */ _jsxDEV("br", {}, void 0, false, {
												fileName: _jsxFileName,
												lineNumber: 627,
												columnNumber: 75
											}, this),
											"Gateway: ",
											s.gateway || "-",
											" · Network: ",
											s.network_type || "-"
										]
									}, void 0, true, {
										fileName: _jsxFileName,
										lineNumber: 622,
										columnNumber: 19
									}, this) }, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 621,
										columnNumber: 17
									}, this)
								}, `${s.site_name}|${s.site_code}`, false, {
									fileName: _jsxFileName,
									lineNumber: 618,
									columnNumber: 15
								}, this))
							]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 605,
							columnNumber: 11
						}, this),
						showTopology && topology.gateways.length > 0 && /* @__PURE__ */ _jsxDEV("div", {
							style: {
								display: "flex",
								gap: 10,
								marginTop: 6,
								marginBottom: 2,
								flexWrap: "wrap",
								alignItems: "center"
							},
							children: [
								/* @__PURE__ */ _jsxDEV("span", {
									style: {
										fontSize: 11,
										color: WH.textMuted,
										fontWeight: 600
									},
									children: "Topology (by Transport):"
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 636,
									columnNumber: 15
								}, this),
								topology.gateways.map((gw) => /* @__PURE__ */ _jsxDEV("span", {
									style: {
										fontSize: 11,
										color: WH.textMuted,
										display: "flex",
										alignItems: "center",
										gap: 4
									},
									children: [/* @__PURE__ */ _jsxDEV("span", { style: {
										width: 14,
										height: 4,
										borderRadius: 2,
										background: gwColor(gw),
										display: "inline-block"
									} }, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 639,
										columnNumber: 19
									}, this), gw]
								}, gw, true, {
									fileName: _jsxFileName,
									lineNumber: 638,
									columnNumber: 17
								}, this)),
								/* @__PURE__ */ _jsxDEV("span", {
									style: {
										fontSize: 10,
										color: WH.textDim
									},
									children: "（线宽≈hub链路 / 细线≈普通链路）"
								}, void 0, false, {
									fileName: _jsxFileName,
									lineNumber: 643,
									columnNumber: 15
								}, this)
							]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 635,
							columnNumber: 13
						}, this),
						/* @__PURE__ */ _jsxDEV("div", {
							style: {
								display: "flex",
								gap: 12,
								marginTop: 8,
								flexWrap: "wrap"
							},
							children: STATUS_ORDER.map((st) => {
								const hidden = hiddenStatuses.has(st);
								return /* @__PURE__ */ _jsxDEV("span", {
									onClick: () => toggleStatusVisible(st),
									title: hidden ? "Click to show on map" : "Click to hide on map",
									style: {
										fontSize: 11,
										cursor: "pointer",
										userSelect: "none",
										color: hidden ? WH.textDim : WH.textMuted,
										opacity: hidden ? .45 : 1,
										textDecoration: hidden ? "line-through" : "none",
										display: "flex",
										alignItems: "center",
										gap: 4
									},
									children: [/* @__PURE__ */ _jsxDEV("span", { style: {
										width: 10,
										height: 10,
										borderRadius: "50%",
										background: STATUS_COLORS[st],
										display: "inline-block",
										opacity: hidden ? .3 : 1
									} }, void 0, false, {
										fileName: _jsxFileName,
										lineNumber: 659,
										columnNumber: 19
									}, this), STATUS_SHORT[st]]
								}, st, true, {
									fileName: _jsxFileName,
									lineNumber: 650,
									columnNumber: 17
								}, this);
							})
						}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 646,
							columnNumber: 11
						}, this)
					]
				}, void 0, true, {
					fileName: _jsxFileName,
					lineNumber: 592,
					columnNumber: 9
				}, this)
			}, void 0, false, {
				fileName: _jsxFileName,
				lineNumber: 591,
				columnNumber: 7
			}, this),
			/* @__PURE__ */ _jsxDEV(DraggableClickModal, {
				open: drillOpen,
				anchor: drillAnchor,
				dark: true,
				onClose: () => setDrillOpen(false),
				title: /* @__PURE__ */ _jsxDEV("span", {
					style: { color: WH.text },
					children: [
						drillTitle,
						" ",
						/* @__PURE__ */ _jsxDEV(Tag, {
							color: "cyan",
							style: { borderRadius: 10 },
							children: [filteredDrillData.length, " records"]
						}, void 0, true, {
							fileName: _jsxFileName,
							lineNumber: 674,
							columnNumber: 62
						}, this)
					]
				}, void 0, true, {
					fileName: _jsxFileName,
					lineNumber: 674,
					columnNumber: 16
				}, this),
				children: [/* @__PURE__ */ _jsxDEV("div", {
					style: {
						display: "flex",
						justifyContent: "space-between",
						marginBottom: 12
					},
					children: [/* @__PURE__ */ _jsxDEV(Input, {
						prefix: /* @__PURE__ */ _jsxDEV(SearchOutlined, {}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 677,
							columnNumber: 26
						}, this),
						placeholder: "Search site / code / region...",
						allowClear: true,
						size: "middle",
						style: { width: 350 },
						value: drillSearch,
						onChange: (e) => setDrillSearch(e.target.value)
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 677,
						columnNumber: 11
					}, this), /* @__PURE__ */ _jsxDEV(Button, {
						type: "primary",
						icon: /* @__PURE__ */ _jsxDEV(DownloadOutlined, {}, void 0, false, {
							fileName: _jsxFileName,
							lineNumber: 679,
							columnNumber: 40
						}, this),
						onClick: exportToExcel,
						disabled: !filteredDrillData.length,
						children: "Export Excel"
					}, void 0, false, {
						fileName: _jsxFileName,
						lineNumber: 679,
						columnNumber: 11
					}, this)]
				}, void 0, true, {
					fileName: _jsxFileName,
					lineNumber: 676,
					columnNumber: 9
				}, this), drillLoading ? /* @__PURE__ */ _jsxDEV(Spin, { style: {
					display: "block",
					margin: "60px auto"
				} }, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 684,
					columnNumber: 11
				}, this) : /* @__PURE__ */ _jsxDEV(Table, {
					dataSource: filteredDrillData,
					columns: drillColumns,
					size: "small",
					rowKey: (r) => r.Site_Name,
					pagination: {
						pageSize: 15,
						size: "small",
						showTotal: (total) => `${total} items`
					},
					scroll: { x: "max-content" }
				}, void 0, false, {
					fileName: _jsxFileName,
					lineNumber: 686,
					columnNumber: 11
				}, this)]
			}, void 0, true, {
				fileName: _jsxFileName,
				lineNumber: 669,
				columnNumber: 7
			}, this)
		]
	}, void 0, true, {
		fileName: _jsxFileName,
		lineNumber: 510,
		columnNumber: 5
	}, this);
}
_s3(PacketLossDashboard, "E39G9m0VjiFMi3ksf5jNZjNqbpM=");
_c4 = PacketLossDashboard;
var _c, _c2, _c3, _c4;
$RefreshReg$(_c, "SectionTitle");
$RefreshReg$(_c2, "MetricExplainPopover");
$RefreshReg$(_c3, "SummaryCard");
$RefreshReg$(_c4, "PacketLossDashboard");
import * as RefreshRuntime from "/myapp/@react-refresh";
const inWebWorker = typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope;
import * as __vite_react_currentExports from "/myapp/src/pages/PacketLossDashboard.tsx?t=1785787726149";
if (import.meta.hot && !inWebWorker) {
  if (!window.$RefreshReg$) {
    throw new Error(
      "@vitejs/plugin-react can't detect preamble. Something is wrong."
    );
  }

  const currentExports = __vite_react_currentExports;
  queueMicrotask(() => {
    RefreshRuntime.registerExportsForReactRefresh("d:/01_RPA/Task/my_app/frontend/src/pages/PacketLossDashboard.tsx", currentExports);
    import.meta.hot.accept((nextExports) => {
      if (!nextExports) return;
      const invalidateMessage = RefreshRuntime.validateRefreshBoundaryAndEnqueueUpdate("d:/01_RPA/Task/my_app/frontend/src/pages/PacketLossDashboard.tsx", currentExports, nextExports);
      if (invalidateMessage) import.meta.hot.invalidate(invalidateMessage);
    });
  });
}
function $RefreshReg$(type, id) { return RefreshRuntime.register(type, "d:/01_RPA/Task/my_app/frontend/src/pages/PacketLossDashboard.tsx" + ' ' + id); }
function $RefreshSig$() { return RefreshRuntime.createSignatureFunctionForTransform(); }

//# sourceMappingURL=data:application/json;base64,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T0FBSyxPQUFNO09BQU8sT0FBTyxFQUFFLGNBQWMsR0FBRztpQkFBNUMsQ0FBZ0Qsa0JBQWtCLFFBQU8sVUFBYTs7Ozs7O0tBQU87Ozs7OztjQUxwSixDQU9FLHdCQUFDLE9BQUQ7S0FBSyxPQUFPO01BQUUsU0FBUztNQUFRLGdCQUFnQjtNQUFpQixjQUFjO0tBQUc7ZUFBakYsQ0FDRSx3QkFBQyxPQUFEO01BQU8sUUFBUSx3QkFBQyxnQkFBRCxDQUFpQjs7Ozs7TUFBRyxhQUFZO01BQWlDO01BQVcsTUFBSztNQUM5RixPQUFPLEVBQUUsT0FBTyxJQUFJO01BQUcsT0FBTztNQUFhLFdBQVUsTUFBSyxlQUFlLEVBQUUsT0FBTyxLQUFLO0tBQUk7Ozs7ZUFDN0Ysd0JBQUMsUUFBRDtNQUFRLE1BQUs7TUFBVSxNQUFNLHdCQUFDLGtCQUFELENBQW1COzs7OztNQUFHLFNBQVM7TUFBZSxVQUFVLENBQUMsa0JBQWtCO2dCQUFRO0tBRXhHOzs7O2FBQ0w7Ozs7O2NBQ0osZUFDQyx3QkFBQyxNQUFELEVBQU0sT0FBTztLQUFFLFNBQVM7S0FBUyxRQUFRO0lBQVksRUFBSTs7OztlQUV6RCx3QkFBQyxPQUFEO0tBQU8sWUFBWTtLQUFtQixTQUFTO0tBQWMsTUFBSztLQUNoRSxTQUFTLE1BQVcsRUFBRTtLQUN0QixZQUFZO01BQUUsVUFBVTtNQUFJLE1BQU07TUFBUyxZQUFZLFVBQWtCLEdBQUcsTUFBTTtLQUFRO0tBQzFGLFFBQVEsRUFBRSxHQUFHLGNBQWM7SUFBSTs7OztZQUVoQjs7Ozs7O0VBQ2xCOzs7Ozs7QUFFVCIsIm5hbWVzIjpbXSwic291cmNlcyI6WyJQYWNrZXRMb3NzRGFzaGJvYXJkLnRzeCJdLCJ2ZXJzaW9uIjozLCJzb3VyY2VzQ29udGVudCI6WyIvLyBQYWNrZXQgTG9zcyBEYXNoYm9hcmQgLSDkuKLljIXnnIvmnb/vvIjlj4LogIMgUmVhbFRpbWUgQWxhcm0gTWFwIOmjjuagvO+8iVxyXG4vLyDmlbDmja7mupA6IGx0ZV9wbC5zcWxpdGUz77yIUkFOIFVNRSBTRFIvSVBSQU4gSVBQRCDkuKLljIXnjofvvIzov5E35aSp5bCP5pe257KS5bqm77yJXHJcbmltcG9ydCB7IHVzZUVmZmVjdCwgdXNlU3RhdGUsIHVzZU1lbW8sIHVzZUNhbGxiYWNrIH0gZnJvbSAncmVhY3QnXHJcbmltcG9ydCB7IENhcmQsIFJvdywgQ29sLCBUYWcsIFNwaW4sIEFsZXJ0LCBFbXB0eSwgVGFibGUsIElucHV0LCBCdXR0b24sIFN3aXRjaCwgUG9wb3ZlciB9IGZyb20gJ2FudGQnXHJcbmltcG9ydCB7XHJcbiAgQWxlcnRPdXRsaW5lZCwgV2FybmluZ091dGxpbmVkLCBFbnZpcm9ubWVudE91dGxpbmVkLFxyXG4gIFBpZUNoYXJ0T3V0bGluZWQsIEJhckNoYXJ0T3V0bGluZWQsIERhc2hib2FyZE91dGxpbmVkLFxyXG4gIERvd25sb2FkT3V0bGluZWQsIFNlYXJjaE91dGxpbmVkLCBSaWdodE91dGxpbmVkLFxyXG4gIENsb2NrQ2lyY2xlT3V0bGluZWQsIENoZWNrQ2lyY2xlT3V0bGluZWQsIERpc2Nvbm5lY3RPdXRsaW5lZCxcclxuICBDb3B5T3V0bGluZWQsIEluZm9DaXJjbGVPdXRsaW5lZCwgQXBhcnRtZW50T3V0bGluZWQsXHJcbn0gZnJvbSAnQGFudC1kZXNpZ24vaWNvbnMnXHJcbmltcG9ydCBSZWFjdEVDaGFydHMgZnJvbSAnZWNoYXJ0cy1mb3ItcmVhY3QnXHJcbmltcG9ydCB7IE1hcENvbnRhaW5lciwgVGlsZUxheWVyLCBDaXJjbGVNYXJrZXIsIFBvcHVwLCBQb2x5bGluZSwgVG9vbHRpcCB9IGZyb20gJ3JlYWN0LWxlYWZsZXQnXHJcbmltcG9ydCAnbGVhZmxldC9kaXN0L2xlYWZsZXQuY3NzJ1xyXG5pbXBvcnQgKiBhcyBYTFNYIGZyb20gJ3hsc3gnXHJcbmltcG9ydCBkYXlqcyBmcm9tICdkYXlqcydcclxuaW1wb3J0IGFwaSBmcm9tICcuLi9hcGknXHJcbmltcG9ydCB7IGNhY2hlZEdldCB9IGZyb20gJy4uL2NhY2hlJ1xyXG5pbXBvcnQgRHJhZ2dhYmxlQ2xpY2tNb2RhbCBmcm9tICcuLi9jb21wb25lbnRzL0RyYWdnYWJsZUNsaWNrTW9kYWwnXHJcblxyXG4vLyA9PT09PT09PT09IFdhcmVob3VzZSDpo47moLzorr7orqHku6TniYzvvIjkuI4gQWxhcm1EYXNoYm9hcmQg5LiA6Ie077yJID09PT09PT09PT1cclxuY29uc3QgV0ggPSB7XHJcbiAgYmc6ICdsaW5lYXItZ3JhZGllbnQoMTgwZGVnLCAjMGExOTI5IDAlLCAjMGQyMTM4IDEwMCUpJyxcclxuICBjYXJkQmc6ICdsaW5lYXItZ3JhZGllbnQoMTQ1ZGVnLCAjMTQxZjMzIDAlLCAjMTEyNTQwIDEwMCUpJyxcclxuICBjYXJkQm9yZGVyOiAnMXB4IHNvbGlkIHJnYmEoMTAwLDI1NSwyMTgsMC4xOCknLFxyXG4gIGNhcmRCb3JkZXJIb3ZlcjogJzFweCBzb2xpZCByZ2JhKDEwMCwyNTUsMjE4LDAuNTUpJyxcclxuICB0ZWFsOiAnIzY0ZmZkYScsXHJcbiAgYmx1ZTogJyM0ZmMzZjcnLFxyXG4gIGluZGlnbzogJyM3OTg2Y2InLFxyXG4gIHRleHQ6ICcjZTZmNGZmJyxcclxuICB0ZXh0TXV0ZWQ6ICcjOTRhM2I4JyxcclxuICB0ZXh0RGltOiAnIzY0NzQ4YicsXHJcbiAgYWNjZW50R3JhZDogJ2xpbmVhci1ncmFkaWVudCgxMzVkZWcsICM2NGZmZGEsICM0ZmMzZjcpJyxcclxufVxyXG5cclxuY29uc3QgU1RBVFVTX09SREVSID0gWydDcml0aWNhbFs+NV0nLCAnTWFqb3JbMS01XScsICdNaW5vclswLjUtMV0nLCAnV2FybmluZ1swLjEtMC41XScsICdObyBQYWNrZXQgbG9zc1s8MC4xXSddXHJcbmNvbnN0IFNUQVRVU19DT0xPUlM6IFJlY29yZDxzdHJpbmcsIHN0cmluZz4gPSB7XHJcbiAgJ0NyaXRpY2FsWz41XSc6ICcjZmY0NzU3JyxcclxuICAnTWFqb3JbMS01XSc6ICcjZmY5MjJiJyxcclxuICAnTWlub3JbMC41LTFdJzogJyNmZmQ0M2InLFxyXG4gICdXYXJuaW5nWzAuMS0wLjVdJzogJyM3NGMwZmMnLFxyXG4gICdObyBQYWNrZXQgbG9zc1s8MC4xXSc6ICcjNTFjZjY2JyxcclxufVxyXG5jb25zdCBTVEFUVVNfU0hPUlQ6IFJlY29yZDxzdHJpbmcsIHN0cmluZz4gPSB7XHJcbiAgJ0NyaXRpY2FsWz41XSc6ICdDcml0aWNhbCcsXHJcbiAgJ01ham9yWzEtNV0nOiAnTWFqb3InLFxyXG4gICdNaW5vclswLjUtMV0nOiAnTWlub3InLFxyXG4gICdXYXJuaW5nWzAuMS0wLjVdJzogJ1dhcm5pbmcnLFxyXG4gICdObyBQYWNrZXQgbG9zc1s8MC4xXSc6ICdPSycsXHJcbn1cclxuXHJcbi8vIOaMh+agh+iuoeeul+ivtOaYju+8iOm8oOagh+aCrOWBnOOAjD/jgI3mn6XnnIvvvIzlj6/lpI3liLbvvIlcclxuY29uc3QgTUVUUklDX0VYUExBSU46IFJlY29yZDxzdHJpbmcsIHN0cmluZz4gPSB7XHJcbiAgJ1RvdGFsIFNpdGVzJzpcclxuICAgICfooqvnurPlhaXkuKLljIXnm5HmjqfnmoTnq5nngrnmgLvmlbDjgIJcXG4nICtcclxuICAgICfmlbDmja7mnaXmupDvvJpQYWNrZXQgTG9zcyBTdGF0dXMgUmVwb3J0IOeahOermeeCueS4u+aVsOaNru+8iGx0ZV9wbC5zcWxpdGUz77yM6L+RIDcg5aSp6YCQ5bCP5pe257KS5bqm77yJ44CCJyxcclxuICAnQ3JpdGljYWwnOlxyXG4gICAgJ+i/kSAyNCDlsI/ml7bmnIDlpKfkuKLljIXnjocgPiA1JSDnmoTnq5nngrnmlbDjgIJcXG4nICtcclxuICAgICforqHnrpfvvJrlj5bor6Xnq5nngrnmnIDov5EgMjQg5bCP5pe26YCQ5bCP5pe25Lii5YyF546H55qE5pyA5aSn5YC877yITGFzdCAxIGRheSBNYXggUEzvvInvvIw+IDUlIOWIpOS4uiBDcml0aWNhbOOAgicsXHJcbiAgJ01ham9yJzpcclxuICAgICfov5EgMjQg5bCP5pe25pyA5aSn5Lii5YyF546H5LuL5LqOIDEl4oCTNSXvvIjlkKvvvInnmoTnq5nngrnmlbDjgIJcXG4nICtcclxuICAgICforqHnrpfvvJpMYXN0IDEgZGF5IE1heCBQTCDokL3lnKggWzEsIDVdIOWMuumXtOWIpOS4uiBNYWpvcuOAgicsXHJcbiAgJ01pbm9yJzpcclxuICAgICfov5EgMjQg5bCP5pe25pyA5aSn5Lii5YyF546H5LuL5LqOIDAuNSXigJMxJe+8iOWQq++8ieeahOermeeCueaVsOOAglxcbicgK1xyXG4gICAgJ+iuoeeul++8mkxhc3QgMSBkYXkgTWF4IFBMIOiQveWcqCBbMC41LCAxXSDljLrpl7TliKTkuLogTWlub3LjgIInLFxyXG4gICdXYXJuaW5nJzpcclxuICAgICfov5EgMjQg5bCP5pe25pyA5aSn5Lii5YyF546H5LuL5LqOIDAuMSXigJMwLjUl77yI5ZCr77yJ55qE56uZ54K55pWw44CCXFxuJyArXHJcbiAgICAn6K6h566X77yaTGFzdCAxIGRheSBNYXggUEwg6JC95ZyoIFswLjEsIDAuNV0g5Yy66Ze05Yik5Li6IFdhcm5pbmfjgIInLFxyXG4gICdObyBQYWNrZXQgbG9zcyc6XHJcbiAgICAn6L+RIDI0IOWwj+aXtuacgOWkp+S4ouWMheeOhyA8IDAuMSUg55qE56uZ54K55pWw77yI6KeG5Li65q2j5bi477yJ44CCXFxuJyArXHJcbiAgICAn6K6h566X77yaTGFzdCAxIGRheSBNYXggUEwgPCAwLjElIOWIpOS4uiBObyBQYWNrZXQgbG9zc+OAgicsXHJcbiAgJ0FmZmVjdGVkIFNpdGVzJzpcclxuICAgICfov5EgNyDlpKnlhoXlh7rnjrDov4fkuKLljIXvvIjoh7PlsJEgMSDkuKrlsI/ml7bkuKLljIXnjocgPiAw77yJ55qE56uZ54K55pWw44CCXFxuJyArXHJcbiAgICAn5LiOIFRvdGFsIFNpdGVzIOWMuuWIq++8mlRvdGFsIFNpdGVzIOS4uue6s+WFpeebkeaOp+eahOermeeCueaAu+aVsO+8m0FmZmVjdGVkIFNpdGVzIOS7hee7n+iuoeWunumZheWPkeeUn+S4ouWMheeahOermeeCueOAglxcbicgK1xyXG4gICAgJ+aVsOaNruadpea6kO+8mmx0ZV9wbC5zcWxpdGUzIOi/kSA3IOWkqemAkOWwj+aXtuS4ouWMheeOh+OAgicsXHJcbiAgJ0RhdGEgR3JhbnVsYXJpdHknOlxyXG4gICAgJ+aVsOaNrueykuW6pu+8mui/kSA3IOWkqemAkOWwj+aXtu+8iFNEUiArIElQUkFOIOeahCBJUFBEIOS4ouWMheeOh++8ieOAglxcbicgK1xyXG4gICAgJ1NEUiA9IOi9r+WumuS5ieaXoOe6v++8iDNHLzJH77yJ77ybSVBSQU4gPSBJUCDljJblm57kvKDmib/ovb3nvZHjgIInLFxyXG59XHJcblxyXG4vLyDmi5PmiZHop4blm77vvJrmjIkgYmFja2hhdWwvdHJhbnNwb3J0IOexu+Wei++8iGdhdGV3YXkg5a2X5q6177yJ6IGa5ZCI56uZ54K577yMXHJcbi8vIOavj+S4qiBnYXRld2F5IOiuoeeul+i0qOW/g+S9nOS4uuOAjOaxh+iBmuiKgueCueOAje+8jOW5tuaKiuavj+S4quaIkOWRmOermeeCuei/nuWIsOWFtuacgOi/keeahOWQjOe9keWFs+mCu+Wxhe+8jFxyXG4vLyDlvaLmiJAgaHViLWFuZC1zcG9rZSDmi5PmiZHjgILku6XkuIvkuLrlkIQgZ2F0ZXdheSDnmoTphY3oibLjgIJcclxuY29uc3QgR1dfQ09MT1JTOiBSZWNvcmQ8c3RyaW5nLCBzdHJpbmc+ID0ge1xyXG4gICdNVyc6ICcjMzZjZmM5JywgICAgICAgICAgICAvLyDlvq7ms6JcclxuICAnU2F0ZWxsaXRlIExpbmsnOiAnI2ZmYzUzZCcsIC8vIOWNq+aYn+mTvui3r1xyXG4gICdJUFJBTic6ICcjOTI1NGRlJywgICAgICAgICAvLyBJUFJBTlxyXG4gICdTdGFydCBMaW5rJzogJyNmZjdhNDUnLCAgICAvLyBTdGFydCBMaW5rXHJcbn1cclxuY29uc3QgZ3dDb2xvciA9IChndzogc3RyaW5nKSA9PiBHV19DT0xPUlNbZ3ddIHx8ICcjOGM4YzhjJ1xyXG5cclxuY29uc3QgZGFya1Rvb2x0aXAgPSAoKSA9PiAoe1xyXG4gIGJhY2tncm91bmRDb2xvcjogJ3JnYmEoMTAsMjUsNDEsMC45NSknLFxyXG4gIGJvcmRlckNvbG9yOiAncmdiYSgxMDAsMjU1LDIxOCwwLjI1KScsXHJcbiAgYm9yZGVyV2lkdGg6IDEsXHJcbiAgdGV4dFN0eWxlOiB7IGNvbG9yOiAnI2U2ZjRmZicsIGZvbnRTaXplOiAxMiB9LFxyXG4gIGV4dHJhQ3NzVGV4dDogJ2JveC1zaGFkb3c6MCA0cHggMTZweCByZ2JhKDAsMCwwLDAuNCk7JyxcclxufSlcclxuY29uc3QgYXhpc0xhYmVsID0gKCkgPT4gKHsgY29sb3I6ICcjOTRhM2I4JywgZm9udFNpemU6IDExIH0pXHJcbmNvbnN0IGF4aXNMaW5lID0gKCkgPT4gKHsgbGluZVN0eWxlOiB7IGNvbG9yOiAnIzIyMzI0ZCcgfSB9KVxyXG5jb25zdCBzcGxpdExpbmUgPSAoKSA9PiAoeyBsaW5lU3R5bGU6IHsgdHlwZTogJ2Rhc2hlZCcgYXMgY29uc3QsIGNvbG9yOiAncmdiYSgyNTUsMjU1LDI1NSwwLjA2KScgfSB9KVxyXG5jb25zdCBDSEFSVF9IRUlHSFQgPSAyODBcclxuXHJcbmNvbnN0IFNlY3Rpb25UaXRsZSA9ICh7IGljb24sIHRpdGxlLCBzdWIgfTogeyBpY29uOiBSZWFjdC5SZWFjdE5vZGU7IHRpdGxlOiBzdHJpbmc7IHN1Yj86IHN0cmluZyB9KSA9PiAoXHJcbiAgPGRpdiBzdHlsZT17e1xyXG4gICAgZGlzcGxheTogJ2ZsZXgnLCBhbGlnbkl0ZW1zOiAnY2VudGVyJywgZ2FwOiAxMCxcclxuICAgIG1hcmdpbjogJzIycHggMCAxNHB4JywgcGFkZGluZzogJzAgMCAxMHB4JyxcclxuICAgIGJvcmRlckJvdHRvbTogJzFweCBzb2xpZCByZ2JhKDEwMCwyNTUsMjE4LDAuMTgpJyxcclxuICB9fT5cclxuICAgIDxzcGFuIHN0eWxlPXt7XHJcbiAgICAgIHdpZHRoOiAyOCwgaGVpZ2h0OiAyOCwgYm9yZGVyUmFkaXVzOiA2LFxyXG4gICAgICBiYWNrZ3JvdW5kOiBXSC5hY2NlbnRHcmFkLFxyXG4gICAgICBkaXNwbGF5OiAnZmxleCcsIGFsaWduSXRlbXM6ICdjZW50ZXInLCBqdXN0aWZ5Q29udGVudDogJ2NlbnRlcicsXHJcbiAgICAgIGNvbG9yOiAnIzA2MjIyZScsIGZvbnRTaXplOiAxNCxcclxuICAgIH19PntpY29ufTwvc3Bhbj5cclxuICAgIDxzcGFuIHN0eWxlPXt7IGZvbnRTaXplOiAxNiwgZm9udFdlaWdodDogNzAwLCBjb2xvcjogV0gudGV4dCwgbGV0dGVyU3BhY2luZzogJy0wLjNweCcgfX0+e3RpdGxlfTwvc3Bhbj5cclxuICAgIHtzdWIgJiYgPHNwYW4gc3R5bGU9e3sgZm9udFNpemU6IDEyLCBjb2xvcjogV0gudGV4dERpbSwgbWFyZ2luTGVmdDogNCB9fT57c3VifTwvc3Bhbj59XHJcbiAgPC9kaXY+XHJcbilcclxuXHJcbi8vIOmAmueUqOOAjOiuoeeul+ivtOaYjuOAjeaCrOWBnOawlOazoe+8iOW4puWkjeWItu+8ieOAguS+m+aMh+agh+WNoeS7peWklueahOWcsOaWue+8iOWmguWktOmDqCBBZmZlY3RlZCBTaXRlcyDmoIfnrb7vvInlpI3nlKhcclxuY29uc3QgTWV0cmljRXhwbGFpblBvcG92ZXIgPSAoeyB0ZXh0LCBjaGlsZHJlbiB9OiB7IHRleHQ6IHN0cmluZzsgY2hpbGRyZW46IFJlYWN0LlJlYWN0Tm9kZSB9KSA9PiB7XHJcbiAgY29uc3QgW2NvcGllZCwgc2V0Q29waWVkXSA9IHVzZVN0YXRlKGZhbHNlKVxyXG4gIGNvbnN0IGNvcHkgPSB1c2VDYWxsYmFjayhhc3luYyAoKSA9PiB7XHJcbiAgICB0cnkge1xyXG4gICAgICBpZiAobmF2aWdhdG9yLmNsaXBib2FyZD8ud3JpdGVUZXh0KSBhd2FpdCBuYXZpZ2F0b3IuY2xpcGJvYXJkLndyaXRlVGV4dCh0ZXh0KVxyXG4gICAgICBlbHNlIHtcclxuICAgICAgICBjb25zdCB0YSA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ3RleHRhcmVhJylcclxuICAgICAgICB0YS52YWx1ZSA9IHRleHQ7IHRhLnN0eWxlLnBvc2l0aW9uID0gJ2ZpeGVkJzsgdGEuc3R5bGUub3BhY2l0eSA9ICcwJ1xyXG4gICAgICAgIGRvY3VtZW50LmJvZHkuYXBwZW5kQ2hpbGQodGEpOyB0YS5zZWxlY3QoKTsgZG9jdW1lbnQuZXhlY0NvbW1hbmQoJ2NvcHknKTsgZG9jdW1lbnQuYm9keS5yZW1vdmVDaGlsZCh0YSlcclxuICAgICAgfVxyXG4gICAgICBzZXRDb3BpZWQodHJ1ZSk7IHNldFRpbWVvdXQoKCkgPT4gc2V0Q29waWVkKGZhbHNlKSwgMTUwMClcclxuICAgIH0gY2F0Y2ggeyAvKiBpZ25vcmUgKi8gfVxyXG4gIH0sIFt0ZXh0XSlcclxuICBpZiAoIXRleHQpIHJldHVybiA8PntjaGlsZHJlbn08Lz5cclxuICByZXR1cm4gKFxyXG4gICAgPFBvcG92ZXIgdHJpZ2dlcj1cImhvdmVyXCIgcGxhY2VtZW50PVwiYm90dG9tXCIgbW91c2VFbnRlckRlbGF5PXswLjF9XHJcbiAgICAgIGNvbnRlbnQ9e1xyXG4gICAgICAgIDxkaXYgc3R5bGU9e3sgbWF4V2lkdGg6IDMwMCwgZm9udFNpemU6IDEyLCBsaW5lSGVpZ2h0OiAxLjcgfX0+XHJcbiAgICAgICAgICA8ZGl2IHN0eWxlPXt7IGNvbG9yOiBXSC50ZXh0TXV0ZWQsIHdoaXRlU3BhY2U6ICdwcmUtbGluZScgfX0+e3RleHR9PC9kaXY+XHJcbiAgICAgICAgICA8QnV0dG9uIHNpemU9XCJzbWFsbFwiIHR5cGU9XCJsaW5rXCIgaWNvbj17PENvcHlPdXRsaW5lZCAvPn0gb25DbGljaz17Y29weX1cclxuICAgICAgICAgICAgc3R5bGU9e3sgcGFkZGluZ0xlZnQ6IDAsIG1hcmdpblRvcDogOCwgaGVpZ2h0OiAnYXV0bycsIGNvbG9yOiBXSC50ZWFsIH19PlxyXG4gICAgICAgICAgICB7Y29waWVkID8gJ+W3suWkjeWItiDinJMnIDogJ+WkjeWItuivtOaYjid9XHJcbiAgICAgICAgICA8L0J1dHRvbj5cclxuICAgICAgICA8L2Rpdj5cclxuICAgICAgfT5cclxuICAgICAge2NoaWxkcmVufVxyXG4gICAgPC9Qb3BvdmVyPlxyXG4gIClcclxufVxyXG5cclxuY29uc3QgU3VtbWFyeUNhcmQgPSAoeyBpY29uLCB2YWx1ZSwgbGFiZWwsIGNvbG9yLCBvbkNsaWNrLCBleHBsYWluIH06IHtcclxuICBpY29uOiBSZWFjdC5SZWFjdE5vZGU7IHZhbHVlOiBzdHJpbmcgfCBudW1iZXI7IGxhYmVsOiBzdHJpbmc7IGNvbG9yOiBzdHJpbmc7IG9uQ2xpY2s6ICgpID0+IHZvaWQ7IGV4cGxhaW4/OiBzdHJpbmdcclxufSkgPT4ge1xyXG4gIGNvbnN0IFtjb3BpZWQsIHNldENvcGllZF0gPSB1c2VTdGF0ZShmYWxzZSlcclxuICBjb25zdCBjb3B5RXhwbGFpbiA9IHVzZUNhbGxiYWNrKGFzeW5jICgpID0+IHtcclxuICAgIGlmICghZXhwbGFpbikgcmV0dXJuXHJcbiAgICB0cnkge1xyXG4gICAgICBpZiAobmF2aWdhdG9yLmNsaXBib2FyZD8ud3JpdGVUZXh0KSB7XHJcbiAgICAgICAgYXdhaXQgbmF2aWdhdG9yLmNsaXBib2FyZC53cml0ZVRleHQoZXhwbGFpbilcclxuICAgICAgfSBlbHNlIHtcclxuICAgICAgICBjb25zdCB0YSA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ3RleHRhcmVhJylcclxuICAgICAgICB0YS52YWx1ZSA9IGV4cGxhaW5cclxuICAgICAgICB0YS5zdHlsZS5wb3NpdGlvbiA9ICdmaXhlZCdcclxuICAgICAgICB0YS5zdHlsZS5vcGFjaXR5ID0gJzAnXHJcbiAgICAgICAgZG9jdW1lbnQuYm9keS5hcHBlbmRDaGlsZCh0YSlcclxuICAgICAgICB0YS5zZWxlY3QoKVxyXG4gICAgICAgIGRvY3VtZW50LmV4ZWNDb21tYW5kKCdjb3B5JylcclxuICAgICAgICBkb2N1bWVudC5ib2R5LnJlbW92ZUNoaWxkKHRhKVxyXG4gICAgICB9XHJcbiAgICAgIHNldENvcGllZCh0cnVlKVxyXG4gICAgICBzZXRUaW1lb3V0KCgpID0+IHNldENvcGllZChmYWxzZSksIDE1MDApXHJcbiAgICB9IGNhdGNoIHsgLyogaWdub3JlICovIH1cclxuICB9LCBbZXhwbGFpbl0pXHJcblxyXG4gIHJldHVybiAoXHJcbiAgICA8Q2FyZCBzaXplPVwic21hbGxcIiBob3ZlcmFibGUgb25DbGljaz17b25DbGlja30gc3R5bGU9e3tcclxuICAgICAgYmFja2dyb3VuZDogV0guY2FyZEJnLCBib3JkZXI6IFdILmNhcmRCb3JkZXIsIGJvcmRlclJhZGl1czogMTIsXHJcbiAgICAgIGN1cnNvcjogJ3BvaW50ZXInLCB0cmFuc2l0aW9uOiAnYWxsIC4ycycsIHBvc2l0aW9uOiAncmVsYXRpdmUnLCBvdmVyZmxvdzogJ2hpZGRlbicsXHJcbiAgICAgIGJveFNoYWRvdzogJzAgNHB4IDE2cHggcmdiYSgwLDAsMCwwLjI1KScsXHJcbiAgICB9fVxyXG4gICAgICBvbk1vdXNlRW50ZXI9e2UgPT4geyAoZS5jdXJyZW50VGFyZ2V0IGFzIEhUTUxFbGVtZW50KS5zdHlsZS5ib3JkZXIgPSBXSC5jYXJkQm9yZGVySG92ZXIgfX1cclxuICAgICAgb25Nb3VzZUxlYXZlPXtlID0+IHsgKGUuY3VycmVudFRhcmdldCBhcyBIVE1MRWxlbWVudCkuc3R5bGUuYm9yZGVyID0gV0guY2FyZEJvcmRlciB9fVxyXG4gICAgPlxyXG4gICAgICA8ZGl2IHN0eWxlPXt7IHBvc2l0aW9uOiAnYWJzb2x1dGUnLCBsZWZ0OiAwLCB0b3A6IDAsIGJvdHRvbTogMCwgd2lkdGg6IDQsIGJhY2tncm91bmQ6IGNvbG9yLCBvcGFjaXR5OiAwLjkgfX0gLz5cclxuICAgICAge2V4cGxhaW4gJiYgKFxyXG4gICAgICAgIDxQb3BvdmVyXHJcbiAgICAgICAgICB0cmlnZ2VyPVwiaG92ZXJcIlxyXG4gICAgICAgICAgcGxhY2VtZW50PVwidG9wXCJcclxuICAgICAgICAgIG1vdXNlRW50ZXJEZWxheT17MC4xfVxyXG4gICAgICAgICAgY29udGVudD17XHJcbiAgICAgICAgICAgIDxkaXYgc3R5bGU9e3sgbWF4V2lkdGg6IDI4MCwgZm9udFNpemU6IDEyLCBsaW5lSGVpZ2h0OiAxLjcgfX0+XHJcbiAgICAgICAgICAgICAgPGRpdiBzdHlsZT17eyBmb250V2VpZ2h0OiA3MDAsIGNvbG9yOiBXSC50ZWFsLCBtYXJnaW5Cb3R0b206IDYgfX0+e2xhYmVsfSDCtyDorqHnrpfor7TmmI48L2Rpdj5cclxuICAgICAgICAgICAgICA8ZGl2IHN0eWxlPXt7IGNvbG9yOiBXSC50ZXh0TXV0ZWQsIHdoaXRlU3BhY2U6ICdwcmUtbGluZScgfX0+e2V4cGxhaW59PC9kaXY+XHJcbiAgICAgICAgICAgICAgPEJ1dHRvbiBzaXplPVwic21hbGxcIiB0eXBlPVwibGlua1wiIGljb249ezxDb3B5T3V0bGluZWQgLz59IG9uQ2xpY2s9e2NvcHlFeHBsYWlufVxyXG4gICAgICAgICAgICAgICAgc3R5bGU9e3sgcGFkZGluZ0xlZnQ6IDAsIG1hcmdpblRvcDogOCwgaGVpZ2h0OiAnYXV0bycsIGNvbG9yOiBXSC50ZWFsIH19PlxyXG4gICAgICAgICAgICAgICAge2NvcGllZCA/ICflt7LlpI3liLYg4pyTJyA6ICflpI3liLbor7TmmI4nfVxyXG4gICAgICAgICAgICAgIDwvQnV0dG9uPlxyXG4gICAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICAgIH1cclxuICAgICAgICA+XHJcbiAgICAgICAgICA8c3BhblxyXG4gICAgICAgICAgICBvbkNsaWNrPXtlID0+IGUuc3RvcFByb3BhZ2F0aW9uKCl9XHJcbiAgICAgICAgICAgIHN0eWxlPXt7IHBvc2l0aW9uOiAnYWJzb2x1dGUnLCB0b3A6IDYsIHJpZ2h0OiA4LCB6SW5kZXg6IDIsIGN1cnNvcjogJ2hlbHAnLCBjb2xvcjogV0gudGV4dERpbSwgZm9udFNpemU6IDEzIH19XHJcbiAgICAgICAgICA+XHJcbiAgICAgICAgICAgIDxJbmZvQ2lyY2xlT3V0bGluZWQgLz5cclxuICAgICAgICAgIDwvc3Bhbj5cclxuICAgICAgICA8L1BvcG92ZXI+XHJcbiAgICAgICl9XHJcbiAgICAgIDxkaXYgc3R5bGU9e3sgZGlzcGxheTogJ2ZsZXgnLCBqdXN0aWZ5Q29udGVudDogJ3NwYWNlLWJldHdlZW4nLCBhbGlnbkl0ZW1zOiAnY2VudGVyJyB9fT5cclxuICAgICAgICA8ZGl2PlxyXG4gICAgICAgICAgPGRpdiBzdHlsZT17eyBmb250U2l6ZTogMzAsIGZvbnRXZWlnaHQ6IDgwMCwgY29sb3IsIGxpbmVIZWlnaHQ6IDEuMiwgdGV4dFNoYWRvdzogYDAgMCAxNHB4ICR7Y29sb3J9NTVgIH19Pnt2YWx1ZX08L2Rpdj5cclxuICAgICAgICAgIDxkaXYgc3R5bGU9e3sgZm9udFNpemU6IDEyLCBjb2xvcjogV0gudGV4dE11dGVkLCBtYXJnaW5Ub3A6IDQsIGZvbnRXZWlnaHQ6IDUwMCB9fT57bGFiZWx9PC9kaXY+XHJcbiAgICAgICAgPC9kaXY+XHJcbiAgICAgICAgPHNwYW4gc3R5bGU9e3sgZm9udFNpemU6IDM4LCBvcGFjaXR5OiAwLjE2LCBjb2xvciB9fT57aWNvbn08L3NwYW4+XHJcbiAgICAgIDwvZGl2PlxyXG4gICAgICA8ZGl2IHN0eWxlPXt7IHRleHRBbGlnbjogJ3JpZ2h0JywgZm9udFNpemU6IDEwLCBjb2xvcjogV0gudGVhbCwgZm9udFdlaWdodDogNjAwLCBtYXJnaW5Ub3A6IDIsIGRpc3BsYXk6ICdmbGV4JywgYWxpZ25JdGVtczogJ2NlbnRlcicsIGp1c3RpZnlDb250ZW50OiAnZmxleC1lbmQnLCBnYXA6IDIgfX0+XHJcbiAgICAgICAg54K55Ye75LiL6ZK7IDxSaWdodE91dGxpbmVkIHN0eWxlPXt7IGZvbnRTaXplOiA5IH19IC8+XHJcbiAgICAgIDwvZGl2PlxyXG4gICAgPC9DYXJkPlxyXG4gIClcclxufVxyXG5cclxuY29uc3Qgc3RyU29ydGVyID0gKGE6IGFueSwgYjogYW55LCBrZXk6IHN0cmluZykgPT4gU3RyaW5nKGFba2V5XSA/PyAnJykubG9jYWxlQ29tcGFyZShTdHJpbmcoYltrZXldID8/ICcnKSlcclxuY29uc3QgZ2V0VW5pcXVlRmlsdGVycyA9IChkYXRhOiBhbnlbXSwga2V5OiBzdHJpbmcpID0+IHtcclxuICBjb25zdCB2YWxzID0gbmV3IFNldDxzdHJpbmc+KClcclxuICBkYXRhLmZvckVhY2gociA9PiB7IGlmIChyW2tleV0gIT0gbnVsbCAmJiByW2tleV0gIT09ICcnKSB2YWxzLmFkZChTdHJpbmcocltrZXldKSkgfSlcclxuICByZXR1cm4gQXJyYXkuZnJvbSh2YWxzKS5tYXAodiA9PiAoeyB0ZXh0OiB2LCB2YWx1ZTogdiB9KSlcclxufVxyXG5cclxuaW50ZXJmYWNlIFBsU2l0ZSB7XHJcbiAgc2l0ZV9uYW1lOiBzdHJpbmc7IHNpdGVfY29kZTogc3RyaW5nOyBsYXQ6IG51bWJlcjsgbG5nOiBudW1iZXJcclxuICByZWdpb246IHN0cmluZzsgcHJvdmluY2VfY291bnR5OiBzdHJpbmc7IGdhdGV3YXk6IHN0cmluZzsgbmV0d29ya190eXBlOiBzdHJpbmdcclxuICBzdGF0dXM6IHN0cmluZzsgbGFzdF9kYXlfbWF4X3BsOiBudW1iZXI7IHRvdGFsX3BsOiBudW1iZXI7IGFmZmVjdGVkX2hvdXJzOiBudW1iZXJcclxufVxyXG5cclxuZXhwb3J0IGRlZmF1bHQgZnVuY3Rpb24gUGFja2V0TG9zc0Rhc2hib2FyZCgpIHtcclxuICBjb25zdCBbbG9hZGluZywgc2V0TG9hZGluZ10gPSB1c2VTdGF0ZSh0cnVlKVxyXG4gIGNvbnN0IFtlcnJvciwgc2V0RXJyb3JdID0gdXNlU3RhdGU8c3RyaW5nIHwgbnVsbD4obnVsbClcclxuICBjb25zdCBbZGF0YSwgc2V0RGF0YV0gPSB1c2VTdGF0ZTxhbnk+KG51bGwpXHJcbiAgY29uc3QgW21hcFNpdGVzLCBzZXRNYXBTaXRlc10gPSB1c2VTdGF0ZTxQbFNpdGVbXT4oW10pXHJcbiAgY29uc3QgW2luY2x1ZGVPaywgc2V0SW5jbHVkZU9rXSA9IHVzZVN0YXRlKGZhbHNlKVxyXG4gIGNvbnN0IFtoaWRkZW5TdGF0dXNlcywgc2V0SGlkZGVuU3RhdHVzZXNdID0gdXNlU3RhdGU8U2V0PHN0cmluZz4+KG5ldyBTZXQoKSlcclxuICAvLyDmi5PmiZHmmL7npLrlvIDlhbPvvJrlvIDlkK/lkI7lpI3nlKggR0lTIE1hcCDnmoTnnJ/lrp7mi5PmiZHpk77ot6/vvIgvYXBpL2dpcy90b3BvbG9nee+8ie+8jOaMieS8oOi+k+exu+Wei+edgOiJslxyXG4gIGNvbnN0IFtzaG93VG9wb2xvZ3ksIHNldFNob3dUb3BvbG9neV0gPSB1c2VTdGF0ZShmYWxzZSlcclxuICBjb25zdCBbZ2lzVG9wb2xvZ3ksIHNldEdpc1RvcG9sb2d5XSA9IHVzZVN0YXRlPGFueVtdPihbXSlcclxuICB1c2VFZmZlY3QoKCkgPT4ge1xyXG4gICAgaWYgKHNob3dUb3BvbG9neSAmJiBnaXNUb3BvbG9neS5sZW5ndGggPT09IDApIHtcclxuICAgICAgYXBpLmdldCgnL2dpcy90b3BvbG9neScpXHJcbiAgICAgICAgLnRoZW4ocmVzID0+IHNldEdpc1RvcG9sb2d5KHJlcy5kYXRhLmxpbmtzIHx8IFtdKSlcclxuICAgICAgICAuY2F0Y2goKCkgPT4ge30pXHJcbiAgICB9XHJcbiAgfSwgW3Nob3dUb3BvbG9neV0pXHJcbiAgY29uc3QgdG9nZ2xlU3RhdHVzVmlzaWJsZSA9IHVzZUNhbGxiYWNrKChzdDogc3RyaW5nKSA9PiB7XHJcbiAgICBzZXRIaWRkZW5TdGF0dXNlcyhwcmV2ID0+IHtcclxuICAgICAgY29uc3QgbmV4dCA9IG5ldyBTZXQocHJldilcclxuICAgICAgaWYgKG5leHQuaGFzKHN0KSkgbmV4dC5kZWxldGUoc3QpOyBlbHNlIG5leHQuYWRkKHN0KVxyXG4gICAgICByZXR1cm4gbmV4dFxyXG4gICAgfSlcclxuICB9LCBbXSlcclxuXHJcbiAgLy8g5LiL6ZK7XHJcbiAgY29uc3QgW2RyaWxsT3Blbiwgc2V0RHJpbGxPcGVuXSA9IHVzZVN0YXRlKGZhbHNlKVxyXG4gIGNvbnN0IFtkcmlsbExvYWRpbmcsIHNldERyaWxsTG9hZGluZ10gPSB1c2VTdGF0ZShmYWxzZSlcclxuICBjb25zdCBbZHJpbGxEYXRhLCBzZXREcmlsbERhdGFdID0gdXNlU3RhdGU8YW55W10+KFtdKVxyXG4gIGNvbnN0IFtkcmlsbFRpdGxlLCBzZXREcmlsbFRpdGxlXSA9IHVzZVN0YXRlKCcnKVxyXG4gIGNvbnN0IFtkcmlsbFNlYXJjaCwgc2V0RHJpbGxTZWFyY2hdID0gdXNlU3RhdGUoJycpXHJcbiAgY29uc3QgW2RyaWxsVG90YWwsIHNldERyaWxsVG90YWxdID0gdXNlU3RhdGUoMClcclxuICBjb25zdCBbZHJpbGxBbmNob3IsIHNldERyaWxsQW5jaG9yXSA9IHVzZVN0YXRlPHsgeDogbnVtYmVyOyB5OiBudW1iZXIgfSB8IG51bGw+KG51bGwpXHJcblxyXG4gIHVzZUVmZmVjdCgoKSA9PiB7XHJcbiAgICBzZXRMb2FkaW5nKHRydWUpXHJcbiAgICBzZXRFcnJvcihudWxsKVxyXG4gICAgUHJvbWlzZS5hbGwoW1xyXG4gICAgICBjYWNoZWRHZXQoJ3BsOm92ZXJ2aWV3JywgKCkgPT4gYXBpLmdldCgnL3BhY2tldC1sb3NzLWRhc2hib2FyZC9vdmVydmlldycpKSxcclxuICAgICAgY2FjaGVkR2V0KGBwbDptYXA6JHtpbmNsdWRlT2t9YCwgKCkgPT4gYXBpLmdldCgnL3BhY2tldC1sb3NzLWRhc2hib2FyZC9tYXAtc2l0ZXMnLCB7IHBhcmFtczogeyBpbmNsdWRlX29rOiBpbmNsdWRlT2sgfSB9KSksXHJcbiAgICBdKVxyXG4gICAgICAudGhlbigoW292LCBtcF0pID0+IHtcclxuICAgICAgICBzZXREYXRhKG92LmRhdGEpXHJcbiAgICAgICAgc2V0TWFwU2l0ZXMobXAuZGF0YS5zaXRlcyB8fCBbXSlcclxuICAgICAgICBzZXRFcnJvcihudWxsKVxyXG4gICAgICB9KVxyXG4gICAgICAuY2F0Y2goZXJyID0+IHsgY29uc29sZS5lcnJvcignUGFja2V0IExvc3MgQVBJIGVycm9yOicsIGVycik7IHNldEVycm9yKGVyci5tZXNzYWdlIHx8ICdGYWlsZWQgdG8gbG9hZCcpIH0pXHJcbiAgICAgIC5maW5hbGx5KCgpID0+IHNldExvYWRpbmcoZmFsc2UpKVxyXG4gIH0sIFtpbmNsdWRlT2tdKVxyXG5cclxuICBjb25zdCBvcGVuRHJpbGxkb3duID0gdXNlQ2FsbGJhY2soKHRyaWdnZXI6IGFueSwgc3RhdHVzOiBzdHJpbmcsIHRpdGxlOiBzdHJpbmcpID0+IHtcclxuICAgIGxldCBhbmNob3I6IHsgeDogbnVtYmVyOyB5OiBudW1iZXIgfSB8IG51bGwgPSBudWxsXHJcbiAgICBpZiAodHJpZ2dlciAmJiB0eXBlb2YgdHJpZ2dlci5jbGllbnRYID09PSAnbnVtYmVyJykge1xyXG4gICAgICBhbmNob3IgPSB7IHg6IHRyaWdnZXIuY2xpZW50WCwgeTogdHJpZ2dlci5jbGllbnRZIH1cclxuICAgIH0gZWxzZSBpZiAodHJpZ2dlcj8uZXZlbnQ/LmV2ZW50ICYmIHR5cGVvZiB0cmlnZ2VyLmV2ZW50LmV2ZW50LmNsaWVudFggPT09ICdudW1iZXInKSB7XHJcbiAgICAgIGFuY2hvciA9IHsgeDogdHJpZ2dlci5ldmVudC5ldmVudC5jbGllbnRYLCB5OiB0cmlnZ2VyLmV2ZW50LmV2ZW50LmNsaWVudFkgfVxyXG4gICAgfVxyXG4gICAgc2V0RHJpbGxBbmNob3IoYW5jaG9yKVxyXG4gICAgc2V0RHJpbGxPcGVuKHRydWUpXHJcbiAgICBzZXREcmlsbExvYWRpbmcodHJ1ZSlcclxuICAgIHNldERyaWxsRGF0YShbXSlcclxuICAgIHNldERyaWxsU2VhcmNoKCcnKVxyXG4gICAgc2V0RHJpbGxUaXRsZSh0aXRsZSlcclxuICAgIGFwaS5nZXQoJy9wYWNrZXQtbG9zcy1kYXNoYm9hcmQvZHJpbGxkb3duJywgeyBwYXJhbXM6IHsgc3RhdHVzLCBsaW1pdDogODAwIH0gfSlcclxuICAgICAgLnRoZW4ocmVzID0+IHtcclxuICAgICAgICBzZXREcmlsbERhdGEocmVzLmRhdGEuZGF0YSB8fCBbXSlcclxuICAgICAgICBzZXREcmlsbFRvdGFsKHJlcy5kYXRhLnRvdGFsIHx8IDApXHJcbiAgICAgIH0pXHJcbiAgICAgIC5jYXRjaCgoKSA9PiBzZXREcmlsbFRpdGxlKCdGYWlsZWQgdG8gbG9hZCBkYXRhJykpXHJcbiAgICAgIC5maW5hbGx5KCgpID0+IHNldERyaWxsTG9hZGluZyhmYWxzZSkpXHJcbiAgfSwgW10pXHJcblxyXG4gIGNvbnN0IGZpbHRlcmVkRHJpbGxEYXRhID0gdXNlTWVtbygoKSA9PiB7XHJcbiAgICBpZiAoIWRyaWxsU2VhcmNoLnRyaW0oKSkgcmV0dXJuIGRyaWxsRGF0YVxyXG4gICAgY29uc3QgbG93ZXIgPSBkcmlsbFNlYXJjaC50b0xvd2VyQ2FzZSgpXHJcbiAgICByZXR1cm4gZHJpbGxEYXRhLmZpbHRlcihyb3cgPT4gT2JqZWN0LnZhbHVlcyhyb3cpLnNvbWUodiA9PiB2ICE9IG51bGwgJiYgU3RyaW5nKHYpLnRvTG93ZXJDYXNlKCkuaW5jbHVkZXMobG93ZXIpKSlcclxuICB9LCBbZHJpbGxEYXRhLCBkcmlsbFNlYXJjaF0pXHJcblxyXG4gIGNvbnN0IGV4cG9ydFRvRXhjZWwgPSB1c2VDYWxsYmFjaygoKSA9PiB7XHJcbiAgICBpZiAoIWZpbHRlcmVkRHJpbGxEYXRhLmxlbmd0aCkgcmV0dXJuXHJcbiAgICBjb25zdCBrZXlzID0gT2JqZWN0LmtleXMoZmlsdGVyZWREcmlsbERhdGFbMF0pXHJcbiAgICBjb25zdCByb3dzID0gZmlsdGVyZWREcmlsbERhdGEubWFwKHJvdyA9PiBrZXlzLm1hcChrID0+IHJvd1trXSA9PSBudWxsID8gJycgOiBTdHJpbmcocm93W2tdKSkpXHJcbiAgICBjb25zdCB3cyA9IFhMU1gudXRpbHMuYW9hX3RvX3NoZWV0KFtrZXlzLCAuLi5yb3dzXSlcclxuICAgIHdzWychY29scyddID0ga2V5cy5tYXAoKCkgPT4gKHsgd2NoOiAxOCB9KSlcclxuICAgIGNvbnN0IHdiID0gWExTWC51dGlscy5ib29rX25ldygpXHJcbiAgICBjb25zdCBmbmFtZSA9IGBQYWNrZXRMb3NzXyR7ZGF5anMoKS5mb3JtYXQoJ1lZWVlNTUREX0hIbW1zcycpfWBcclxuICAgIFhMU1gudXRpbHMuYm9va19hcHBlbmRfc2hlZXQod2IsIHdzLCBmbmFtZS5zdWJzdHJpbmcoMCwgMzEpKVxyXG4gICAgWExTWC53cml0ZUZpbGUod2IsIGAke2ZuYW1lfS54bHN4YClcclxuICB9LCBbZmlsdGVyZWREcmlsbERhdGFdKVxyXG5cclxuICBjb25zdCBkcmlsbENvbHVtbnMgPSB1c2VNZW1vKCgpID0+IHtcclxuICAgIGlmICghZHJpbGxEYXRhLmxlbmd0aCkgcmV0dXJuIFtdXHJcbiAgICByZXR1cm4gT2JqZWN0LmtleXMoZHJpbGxEYXRhWzBdKS5tYXAoayA9PiAoe1xyXG4gICAgICB0aXRsZTogay5yZXBsYWNlKC9fL2csICcgJyksXHJcbiAgICAgIGRhdGFJbmRleDogayxcclxuICAgICAga2V5OiBrLFxyXG4gICAgICB3aWR0aDogMTMwLFxyXG4gICAgICBlbGxpcHNpczogdHJ1ZSxcclxuICAgICAgc29ydGVyOiAoYTogYW55LCBiOiBhbnkpID0+IHN0clNvcnRlcihhLCBiLCBrKSxcclxuICAgICAgZmlsdGVyczogZ2V0VW5pcXVlRmlsdGVycyhkcmlsbERhdGEsIGspLFxyXG4gICAgICBvbkZpbHRlcjogKHY6IGFueSwgcjogYW55KSA9PiBTdHJpbmcocltrXSkgPT09IHYsXHJcbiAgICB9KSlcclxuICB9LCBbZHJpbGxEYXRhXSlcclxuXHJcbiAgLy8gPT09PT09PT09PSDlm77ooajphY3nva4gPT09PT09PT09PVxyXG4gIGNvbnN0IHN0YXR1c1BpZU9wdGlvbiA9IHVzZU1lbW8oKCkgPT4ge1xyXG4gICAgaWYgKCFkYXRhPy5zdGF0dXNfcGllKSByZXR1cm4ge31cclxuICAgIHJldHVybiB7XHJcbiAgICAgIHRvb2x0aXA6IHsgLi4uZGFya1Rvb2x0aXAoKSwgdHJpZ2dlcjogJ2l0ZW0nLCBmb3JtYXR0ZXI6ICd7Yn08YnIvPntjfSBzaXRlcyAoe2R9JSknIH0sXHJcbiAgICAgIGxlZ2VuZDogeyBvcmllbnQ6ICd2ZXJ0aWNhbCcsIHJpZ2h0OiAwLCB0b3A6ICdjZW50ZXInLCB0ZXh0U3R5bGU6IHsgZm9udFNpemU6IDEwLCBjb2xvcjogV0gudGV4dE11dGVkIH0sIGl0ZW1XaWR0aDogMTAsIGl0ZW1IZWlnaHQ6IDEwIH0sXHJcbiAgICAgIHNlcmllczogW3tcclxuICAgICAgICB0eXBlOiAncGllJywgcmFkaXVzOiBbJzM4JScsICc2NSUnXSwgY2VudGVyOiBbJzM4JScsICc1MCUnXSxcclxuICAgICAgICBkYXRhOiBkYXRhLnN0YXR1c19waWUubWFwKChzOiBhbnkpID0+ICh7XHJcbiAgICAgICAgICBuYW1lOiBzLnN0YXR1cywgdmFsdWU6IHMuY291bnQsIGl0ZW1TdHlsZTogeyBjb2xvcjogU1RBVFVTX0NPTE9SU1tzLnN0YXR1c10gfHwgV0gudGVhbCB9LFxyXG4gICAgICAgIH0pKSxcclxuICAgICAgICBsYWJlbDogeyBmb250U2l6ZTogMTAsIGNvbG9yOiBXSC50ZXh0LCBmb3JtYXR0ZXI6ICd7Y30nIH0sXHJcbiAgICAgICAgZW1waGFzaXM6IHsgaXRlbVN0eWxlOiB7IHNoYWRvd0JsdXI6IDEwLCBzaGFkb3dDb2xvcjogJ3JnYmEoMTAwLDI1NSwyMTgsMC40KScgfSB9LFxyXG4gICAgICB9XSxcclxuICAgIH1cclxuICB9LCBbZGF0YV0pXHJcblxyXG4gIGNvbnN0IHJlZ2lvbk9wdGlvbiA9IHVzZU1lbW8oKCkgPT4ge1xyXG4gICAgaWYgKCFkYXRhPy5yZWdpb25fZGlzdCkgcmV0dXJuIHt9XHJcbiAgICBjb25zdCBlbnRyaWVzID0gT2JqZWN0LmVudHJpZXMoZGF0YS5yZWdpb25fZGlzdCkgYXMgW3N0cmluZywgYW55XVtdXHJcbiAgICBpZiAoIWVudHJpZXMubGVuZ3RoKSByZXR1cm4ge31cclxuICAgIHJldHVybiB7XHJcbiAgICAgIHRvb2x0aXA6IHtcclxuICAgICAgICAuLi5kYXJrVG9vbHRpcCgpLCB0cmlnZ2VyOiAnYXhpcycsIGF4aXNQb2ludGVyOiB7IHR5cGU6ICdzaGFkb3cnIH0sXHJcbiAgICAgICAgZm9ybWF0dGVyOiAocHM6IGFueVtdKSA9PiB7XHJcbiAgICAgICAgICBjb25zdCBpZHggPSBwc1swXS5kYXRhSW5kZXhcclxuICAgICAgICAgIGNvbnN0IGIgPSBlbnRyaWVzW2lkeF1bMV1cclxuICAgICAgICAgIHJldHVybiBgPGRpdiBzdHlsZT1cImZvbnQtd2VpZ2h0OjYwMDttYXJnaW4tYm90dG9tOjRweFwiPiR7ZW50cmllc1tpZHhdWzBdfTwvZGl2PmAgK1xyXG4gICAgICAgICAgICBgQWZmZWN0ZWQgU2l0ZXM6IDxzdHJvbmc+JHtiLnNpdGVzfTwvc3Ryb25nPjxici8+Q3JpdGljYWw6IDxzdHJvbmc+JHtiLmNyaXRpY2FsfTwvc3Ryb25nPjxici8+TWF4IFBMOiA8c3Ryb25nPiR7Yi5tYXhfcGwudG9GaXhlZCgyKX0lPC9zdHJvbmc+YFxyXG4gICAgICAgIH0sXHJcbiAgICAgIH0sXHJcbiAgICAgIGdyaWQ6IHsgbGVmdDogNDAsIHJpZ2h0OiAyMCwgdG9wOiAxMCwgYm90dG9tOiA0MCB9LFxyXG4gICAgICB4QXhpczogeyB0eXBlOiAnY2F0ZWdvcnknLCBkYXRhOiBlbnRyaWVzLm1hcCgoW2tdKSA9PiBrKSwgYXhpc0xhYmVsOiB7IC4uLmF4aXNMYWJlbCgpLCByb3RhdGU6IDMwIH0sIGF4aXNMaW5lOiBheGlzTGluZSgpIH0sXHJcbiAgICAgIHlBeGlzOiB7IHR5cGU6ICd2YWx1ZScsIHNwbGl0TGluZTogc3BsaXRMaW5lKCksIGF4aXNMYWJlbDogYXhpc0xhYmVsKCkgfSxcclxuICAgICAgc2VyaWVzOiBbe1xyXG4gICAgICAgIHR5cGU6ICdiYXInLCBiYXJNYXhXaWR0aDogMjgsXHJcbiAgICAgICAgZGF0YTogZW50cmllcy5tYXAoKFssIGJdLCBpKSA9PiAoe1xyXG4gICAgICAgICAgdmFsdWU6IGIuc2l0ZXMsXHJcbiAgICAgICAgICBpdGVtU3R5bGU6IHtcclxuICAgICAgICAgICAgY29sb3I6IHsgdHlwZTogJ2xpbmVhcicsIHg6IDAsIHk6IDAsIHgyOiAwLCB5MjogMSwgY29sb3JTdG9wczogW3sgb2Zmc2V0OiAwLCBjb2xvcjogaSA9PT0gMCA/ICcjZmY0NzU3JyA6ICcjNjRmZmRhJyB9LCB7IG9mZnNldDogMSwgY29sb3I6ICcjMGQyMTM4JyB9XSB9LFxyXG4gICAgICAgICAgICBib3JkZXJSYWRpdXM6IFs0LCA0LCAwLCAwXSxcclxuICAgICAgICAgIH0sXHJcbiAgICAgICAgfSkpLFxyXG4gICAgICAgIGxhYmVsOiB7IHNob3c6IHRydWUsIHBvc2l0aW9uOiAndG9wJywgZm9udFNpemU6IDEwLCBjb2xvcjogV0gudGV4dE11dGVkLCBmb250V2VpZ2h0OiA2MDAgfSxcclxuICAgICAgfV0sXHJcbiAgICB9XHJcbiAgfSwgW2RhdGFdKVxyXG5cclxuICBjb25zdCB0cmVuZE9wdGlvbiA9IHVzZU1lbW8oKCkgPT4ge1xyXG4gICAgaWYgKCFkYXRhPy5kYWlseV90cmVuZD8ubGVuZ3RoKSByZXR1cm4ge31cclxuICAgIGNvbnN0IGRheXMgPSBkYXRhLmRhaWx5X3RyZW5kLm1hcCgoZDogYW55KSA9PiBkLmRheS5zbGljZSg1KSlcclxuICAgIHJldHVybiB7XHJcbiAgICAgIHRvb2x0aXA6IHsgLi4uZGFya1Rvb2x0aXAoKSwgdHJpZ2dlcjogJ2F4aXMnIH0sXHJcbiAgICAgIGxlZ2VuZDogeyBkYXRhOiBbJ01lZGlhbiBQTCAoJSknLCAnQWZmZWN0ZWQgU2l0ZXMnXSwgYm90dG9tOiAwLCB0ZXh0U3R5bGU6IHsgZm9udFNpemU6IDExLCBjb2xvcjogV0gudGV4dE11dGVkIH0gfSxcclxuICAgICAgZ3JpZDogeyBsZWZ0OiA1MCwgcmlnaHQ6IDUwLCB0b3A6IDIwLCBib3R0b206IDUwIH0sXHJcbiAgICAgIHhBeGlzOiB7IHR5cGU6ICdjYXRlZ29yeScsIGRhdGE6IGRheXMsIGF4aXNMYWJlbDogYXhpc0xhYmVsKCksIGF4aXNMaW5lOiBheGlzTGluZSgpIH0sXHJcbiAgICAgIHlBeGlzOiBbXHJcbiAgICAgICAgeyB0eXBlOiAndmFsdWUnLCBuYW1lOiAnUEwgJScsIHNwbGl0TGluZTogc3BsaXRMaW5lKCksIGF4aXNMYWJlbDogYXhpc0xhYmVsKCkgfSxcclxuICAgICAgICB7IHR5cGU6ICd2YWx1ZScsIG5hbWU6ICdTaXRlcycsIHNwbGl0TGluZTogeyBzaG93OiBmYWxzZSB9LCBheGlzTGFiZWw6IGF4aXNMYWJlbCgpIH0sXHJcbiAgICAgIF0sXHJcbiAgICAgIHNlcmllczogW1xyXG4gICAgICAgIHtcclxuICAgICAgICAgIG5hbWU6ICdNZWRpYW4gUEwgKCUpJywgdHlwZTogJ2JhcicsIGJhck1heFdpZHRoOiAyMixcclxuICAgICAgICAgIGRhdGE6IGRhdGEuZGFpbHlfdHJlbmQubWFwKChkOiBhbnkpID0+IGQubWVkaWFuX3BsKSxcclxuICAgICAgICAgIGl0ZW1TdHlsZToge1xyXG4gICAgICAgICAgICBjb2xvcjogeyB0eXBlOiAnbGluZWFyJywgeDogMCwgeTogMCwgeDI6IDAsIHkyOiAxLCBjb2xvclN0b3BzOiBbeyBvZmZzZXQ6IDAsIGNvbG9yOiAnIzY0ZmZkYScgfSwgeyBvZmZzZXQ6IDEsIGNvbG9yOiAnIzRmYzNmNycgfV0gfSxcclxuICAgICAgICAgICAgYm9yZGVyUmFkaXVzOiBbNCwgNCwgMCwgMF0sXHJcbiAgICAgICAgICB9LFxyXG4gICAgICAgICAgbGFiZWw6IHsgc2hvdzogdHJ1ZSwgcG9zaXRpb246ICd0b3AnLCBmb250U2l6ZTogMTAsIGNvbG9yOiBXSC50ZXh0TXV0ZWQsIGZvcm1hdHRlcjogKHA6IGFueSkgPT4gYCR7cC52YWx1ZX0lYCB9LFxyXG4gICAgICAgIH0sXHJcbiAgICAgICAge1xyXG4gICAgICAgICAgbmFtZTogJ0FmZmVjdGVkIFNpdGVzJywgdHlwZTogJ2xpbmUnLCB5QXhpc0luZGV4OiAxLCBzbW9vdGg6IHRydWUsXHJcbiAgICAgICAgICBkYXRhOiBkYXRhLmRhaWx5X3RyZW5kLm1hcCgoZDogYW55KSA9PiBkLmFmZmVjdGVkX3NpdGVzKSxcclxuICAgICAgICAgIGxpbmVTdHlsZTogeyBjb2xvcjogJyNmZjkyMmInLCB3aWR0aDogMiB9LCBpdGVtU3R5bGU6IHsgY29sb3I6ICcjZmY5MjJiJyB9LCBzeW1ib2xTaXplOiA2LFxyXG4gICAgICAgIH0sXHJcbiAgICAgIF0sXHJcbiAgICB9XHJcbiAgfSwgW2RhdGFdKVxyXG5cclxuICBjb25zdCB0b3BTaXRlc09wdGlvbiA9IHVzZU1lbW8oKCkgPT4ge1xyXG4gICAgaWYgKCFkYXRhPy50b3Bfc2l0ZXM/Lmxlbmd0aCkgcmV0dXJuIHt9XHJcbiAgICBjb25zdCBzaXRlcyA9IGRhdGEudG9wX3NpdGVzLnNsaWNlKDAsIDEyKS5yZXZlcnNlKClcclxuICAgIHJldHVybiB7XHJcbiAgICAgIHRvb2x0aXA6IHtcclxuICAgICAgICAuLi5kYXJrVG9vbHRpcCgpLCB0cmlnZ2VyOiAnYXhpcycsIGF4aXNQb2ludGVyOiB7IHR5cGU6ICdzaGFkb3cnIH0sXHJcbiAgICAgICAgZm9ybWF0dGVyOiAocHM6IGFueVtdKSA9PiB7XHJcbiAgICAgICAgICBjb25zdCBpZHggPSBwc1swXS5kYXRhSW5kZXhcclxuICAgICAgICAgIGNvbnN0IHMgPSBzaXRlc1tpZHhdXHJcbiAgICAgICAgICByZXR1cm4gYDxkaXYgc3R5bGU9XCJmb250LXdlaWdodDo2MDA7bWFyZ2luLWJvdHRvbTo0cHhcIj4ke3Muc2l0ZV9uYW1lfTwvZGl2PmAgK1xyXG4gICAgICAgICAgICBgU3RhdHVzOiA8c3Ryb25nPiR7U1RBVFVTX1NIT1JUW3Muc3RhdHVzXSB8fCBzLnN0YXR1c308L3N0cm9uZz48YnIvPmAgK1xyXG4gICAgICAgICAgICBgTGFzdC0xLWRheSBNZWRpYW4gUEw6IDxzdHJvbmc+JHtzLmxhc3RfZGF5X21lZGlhbl9wbH0lPC9zdHJvbmc+PGJyLz5gICtcclxuICAgICAgICAgICAgYExhc3QtMS1kYXkgTWF4IFBMOiAke3MubGFzdF9kYXlfbWF4X3BsfSU8YnIvPmAgK1xyXG4gICAgICAgICAgICBgQWZmZWN0ZWQgSG91cnM6IDxzdHJvbmc+JHtzLmFmZmVjdGVkX2hvdXJzfTwvc3Ryb25nPjxici8+UmVnaW9uOiAke3MucmVnaW9uIHx8ICctJ31gXHJcbiAgICAgICAgfSxcclxuICAgICAgfSxcclxuICAgICAgZ3JpZDogeyBsZWZ0OiAyMCwgcmlnaHQ6IDYwLCB0b3A6IDEwLCBib3R0b206IDEwIH0sXHJcbiAgICAgIHhBeGlzOiB7IHR5cGU6ICd2YWx1ZScsIHNwbGl0TGluZTogc3BsaXRMaW5lKCksIGF4aXNMYWJlbDogYXhpc0xhYmVsKCkgfSxcclxuICAgICAgeUF4aXM6IHtcclxuICAgICAgICB0eXBlOiAnY2F0ZWdvcnknLFxyXG4gICAgICAgIGRhdGE6IHNpdGVzLm1hcCgoczogYW55KSA9PiBzLnNpdGVfbmFtZS5sZW5ndGggPiAxOCA/IHMuc2l0ZV9uYW1lLnNsaWNlKDAsIDE2KSArICcuLicgOiBzLnNpdGVfbmFtZSksXHJcbiAgICAgICAgYXhpc0xhYmVsOiB7IC4uLmF4aXNMYWJlbCgpLCBjb2xvcjogV0gudGV4dCB9LCBheGlzTGluZTogYXhpc0xpbmUoKSxcclxuICAgICAgfSxcclxuICAgICAgc2VyaWVzOiBbe1xyXG4gICAgICAgIHR5cGU6ICdiYXInLCBiYXJNYXhXaWR0aDogMTYsXHJcbiAgICAgICAgZGF0YTogc2l0ZXMubWFwKChzOiBhbnkpID0+ICh7XHJcbiAgICAgICAgICB2YWx1ZTogcy5sYXN0X2RheV9tZWRpYW5fcGwsXHJcbiAgICAgICAgICBpdGVtU3R5bGU6IHsgY29sb3I6IFNUQVRVU19DT0xPUlNbcy5zdGF0dXNdIHx8IFdILnRlYWwsIGJvcmRlclJhZGl1czogWzAsIDQsIDQsIDBdIH0sXHJcbiAgICAgICAgfSkpLFxyXG4gICAgICAgIGxhYmVsOiB7IHNob3c6IHRydWUsIHBvc2l0aW9uOiAncmlnaHQnLCBmb250U2l6ZTogMTAsIGNvbG9yOiBXSC50ZXh0TXV0ZWQsIGZvcm1hdHRlcjogKHA6IGFueSkgPT4gYCR7cC52YWx1ZX0lYCB9LFxyXG4gICAgICB9XSxcclxuICAgIH1cclxuICB9LCBbZGF0YV0pXHJcblxyXG4gIC8vIOWbvuS+i+i/h+a7pO+8mumakOiXj+mAieS4reeahOeKtuaAgSDihpIg5Zyw5Zu+5LiK5LiN5riy5p+T5a+55bqU56uZ54K5XHJcbiAgLy8g5b+F6aG75pS+5ZyoIGVhcmx5LXJldHVybiDkuYvliY3vvIzkv53or4EgaG9vayDosIPnlKjpobrluo/lnKjmr4/mrKHmuLLmn5Ppg73kuIDoh7TvvIjlkKbliJnkvJrmlLnlj5ggaG9vayDmlbDph48g4oaSIOe7hOS7tuW0qea6g++8iVxyXG4gIGNvbnN0IHZpc2libGVTaXRlcyA9IHVzZU1lbW8oXHJcbiAgICAoKSA9PiBtYXBTaXRlcy5maWx0ZXIocyA9PiAhaGlkZGVuU3RhdHVzZXMuaGFzKHMuc3RhdHVzKSksXHJcbiAgICBbbWFwU2l0ZXMsIGhpZGRlblN0YXR1c2VzXSxcclxuICApXHJcblxyXG4gIC8vIOaLk+aJke+8muWkjeeUqCBHSVMgTWFwIOeahOecn+WunumTvui3r++8iC9hcGkvZ2lzL3RvcG9sb2d577yJ77yM5oyJ5Lyg6L6T57G75Z6L77yIZ2F0ZXdhee+8ieedgOiJsuOAglxyXG4gIC8vIOeUqOOAjOWPr+ingeermeeCueeahOWdkOaghyDihpIgZ2F0ZXdheeOAjeWwsei/keWMuemFjemTvui3r+S4pOerr++8jOWIpOWumuivpemTvui3r+WxnuS6juWTquenjeS8oOi+k+exu+Wei+W5tuWPluiJsuOAglxyXG4gIC8vIOS7hee7mOWItuiHs+WwkeS4gOerr+iQveWcqOW9k+WJjeWPr+ingSBQTCDnq5nngrnlhoXnmoTpk77ot6/vvIjpmo/lm77kvovmmL7pmpDogZTliqjvvInjgILmlL7lnKggZWFybHktcmV0dXJuIOWJje+8jOS/neaMgSBob29rIOmhuuW6j+eos+WumuOAglxyXG4gIGNvbnN0IHRvcG9sb2d5ID0gdXNlTWVtbygoKSA9PiB7XHJcbiAgICBjb25zdCBwdHM6IHsgbGF0OiBudW1iZXI7IGxuZzogbnVtYmVyOyBndzogc3RyaW5nIH1bXSA9IFtdXHJcbiAgICBmb3IgKGNvbnN0IHMgb2YgdmlzaWJsZVNpdGVzKSB7XHJcbiAgICAgIGlmIChzLmxhdCAhPSBudWxsICYmIHMubG5nICE9IG51bGwpIHB0cy5wdXNoKHsgbGF0OiBzLmxhdCwgbG5nOiBzLmxuZywgZ3c6IHMuZ2F0ZXdheSB8fCAnJyB9KVxyXG4gICAgfVxyXG4gICAgY29uc3QgVEggPSAwLjAwNiAvLyDiiYggNjAwbSDlrrnlt67vvIzpgb/lhY3mta7ngrkv5qC85byP5beu5byC5a+86Ie05Yy56YWN5LiN5LiKXHJcbiAgICBjb25zdCBtYXRjaEd3ID0gKGxhdDogbnVtYmVyLCBsbmc6IG51bWJlcik6IHN0cmluZyA9PiB7XHJcbiAgICAgIGxldCBiZXN0ID0gJyc7IGxldCBiZCA9IFRIICogVEhcclxuICAgICAgZm9yIChjb25zdCBwIG9mIHB0cykge1xyXG4gICAgICAgIGNvbnN0IGQgPSAocC5sYXQgLSBsYXQpICoqIDIgKyAocC5sbmcgLSBsbmcpICoqIDJcclxuICAgICAgICBpZiAoZCA8IGJkKSB7IGJkID0gZDsgYmVzdCA9IHAuZ3cgfVxyXG4gICAgICB9XHJcbiAgICAgIHJldHVybiBiZXN0XHJcbiAgICB9XHJcbiAgICBjb25zdCBlZGdlczogeyBwb3NpdGlvbnM6IFtbbnVtYmVyLCBudW1iZXJdLCBbbnVtYmVyLCBudW1iZXJdXTsgY29sb3I6IHN0cmluZzsgaXNIdWI6IGJvb2xlYW4gfVtdID0gW11cclxuICAgIGNvbnN0IGd3U2VlbiA9IG5ldyBTZXQ8c3RyaW5nPigpXHJcbiAgICBmb3IgKGNvbnN0IGwgb2YgZ2lzVG9wb2xvZ3kpIHtcclxuICAgICAgY29uc3QgZ3cgPSBtYXRjaEd3KGwubGF0X2EsIGwubG5nX2EpIHx8IG1hdGNoR3cobC5sYXRfYiwgbC5sbmdfYilcclxuICAgICAgaWYgKCFndykgY29udGludWUgLy8g5Lik56uv6YO95LiN5Zyo5b2T5YmN5Y+v6KeBIFBMIOermeeCueWGhSDihpIg6Lez6L+HXHJcbiAgICAgIGd3U2Vlbi5hZGQoZ3cpXHJcbiAgICAgIGVkZ2VzLnB1c2goe1xyXG4gICAgICAgIHBvc2l0aW9uczogW1tsLmxhdF9hLCBsLmxuZ19hXSwgW2wubGF0X2IsIGwubG5nX2JdXSxcclxuICAgICAgICBjb2xvcjogZ3dDb2xvcihndyksXHJcbiAgICAgICAgaXNIdWI6ICEhbC5pc19odWJfbGluayxcclxuICAgICAgfSlcclxuICAgIH1cclxuICAgIHJldHVybiB7IGVkZ2VzLCBnYXRld2F5czogWy4uLmd3U2Vlbl0gfVxyXG4gIH0sIFt2aXNpYmxlU2l0ZXMsIGdpc1RvcG9sb2d5XSlcclxuXHJcbiAgLy8gPT09PT09PT09PSDmuLLmn5MgPT09PT09PT09PVxyXG4gIGlmIChsb2FkaW5nKSByZXR1cm4gKFxyXG4gICAgPGRpdiBzdHlsZT17eyBiYWNrZ3JvdW5kOiBXSC5iZywgYm9yZGVyUmFkaXVzOiAxMiwgdGV4dEFsaWduOiAnY2VudGVyJywgcGFkZGluZzogNjAgfX0+XHJcbiAgICAgIDxTcGluIHNpemU9XCJsYXJnZVwiIC8+XHJcbiAgICAgIDxkaXYgc3R5bGU9e3sgbWFyZ2luVG9wOiAxMiwgY29sb3I6IFdILnRleHRNdXRlZCB9fT5Mb2FkaW5nIFBhY2tldCBMb3NzIERhc2hib2FyZC4uLjwvZGl2PlxyXG4gICAgPC9kaXY+XHJcbiAgKVxyXG4gIGlmIChlcnJvcikgcmV0dXJuIDxBbGVydCB0eXBlPVwiZXJyb3JcIiBtZXNzYWdlPVwiRmFpbGVkIHRvIGxvYWQgUGFja2V0IExvc3MgRGFzaGJvYXJkXCIgZGVzY3JpcHRpb249e2Vycm9yfSBzaG93SWNvbiBzdHlsZT17eyBtYXJnaW46IDE2IH19IC8+XHJcbiAgaWYgKCFkYXRhKSByZXR1cm4gPEVtcHR5IGRlc2NyaXB0aW9uPVwiTm8gcGFja2V0IGxvc3MgZGF0YSBhdmFpbGFibGUgKHJ1biB0YXNrOiBwYWNrZXRfbG9zc19zeW5jKVwiIC8+XHJcblxyXG4gIGNvbnN0IHNjID0gZGF0YS5zdGF0dXNfY291bnRzIHx8IHt9XHJcbiAgY29uc3QgZm10ID0gKG46IG51bWJlcikgPT4gKG4gPz8gMCkudG9Mb2NhbGVTdHJpbmcoKVxyXG4gIGNvbnN0IHBhZ2VXcmFwOiBSZWFjdC5DU1NQcm9wZXJ0aWVzID0geyBiYWNrZ3JvdW5kOiBXSC5iZywgYm9yZGVyUmFkaXVzOiAxMiwgcGFkZGluZzogNCwgbWluSGVpZ2h0OiAnY2FsYygxMDB2aCAtIDExMHB4KScgfVxyXG4gIGNvbnN0IGNhcmRXcmFwOiBSZWFjdC5DU1NQcm9wZXJ0aWVzID0geyBiYWNrZ3JvdW5kOiBXSC5jYXJkQmcsIGJvcmRlcjogV0guY2FyZEJvcmRlciwgYm9yZGVyUmFkaXVzOiAxMiwgYm94U2hhZG93OiAnMCA0cHggMTZweCByZ2JhKDAsMCwwLDAuMjUpJyB9XHJcbiAgY29uc3QgY2hhcnRDbGljayA9ICh0aXRsZVByZWZpeDogc3RyaW5nKSA9PiAocDogYW55KSA9PiBvcGVuRHJpbGxkb3duKHAsIHAubmFtZSwgYCR7dGl0bGVQcmVmaXh9ID0gJHtTVEFUVVNfU0hPUlRbcC5uYW1lXSB8fCBwLm5hbWV9YClcclxuXHJcbiAgcmV0dXJuIChcclxuICAgIDxkaXYgc3R5bGU9e3sgLi4ucGFnZVdyYXAsIGRpc3BsYXk6ICdmbGV4JywgZmxleERpcmVjdGlvbjogJ3JvdycsIGdhcDogMTIsIGFsaWduSXRlbXM6ICdmbGV4LXN0YXJ0JyB9fT5cclxuICAgICAgey8qID09PT09IOW3puS+pyAyLzPvvJrlhbbkvZnnu4Tku7bvvIzmjpLliJfpobrluo/kuI3lj5ggPT09PT0gKi99XHJcbiAgICAgIDxkaXYgc3R5bGU9e3sgZmxleDogJzEgMSAwJywgbWluV2lkdGg6IDAsIGRpc3BsYXk6ICdmbGV4JywgZmxleERpcmVjdGlvbjogJ2NvbHVtbicsIGdhcDogNCB9fT5cclxuICAgICAgey8qIDEuIOWktOmDqOaoquW5hSAqL31cclxuICAgICAgPENhcmQgc2l6ZT1cInNtYWxsXCIgc3R5bGU9e3tcclxuICAgICAgICBiYWNrZ3JvdW5kOiAnbGluZWFyLWdyYWRpZW50KDEzNWRlZywgIzEwMWEyZSAwJSwgIzExMjU0MCAxMDAlKScsXHJcbiAgICAgICAgYm9yZGVyTGVmdDogJzRweCBzb2xpZCAjZmY0NzU3JyxcclxuICAgICAgICBib3JkZXJSYWRpdXM6IDEyLCBib3hTaGFkb3c6ICcwIDRweCAxNnB4IHJnYmEoMCwwLDAsMC4zKScsIG1hcmdpbkJvdHRvbTogNCxcclxuICAgICAgfX0+XHJcbiAgICAgICAgPGRpdiBzdHlsZT17eyBkaXNwbGF5OiAnZmxleCcsIGFsaWduSXRlbXM6ICdjZW50ZXInLCBqdXN0aWZ5Q29udGVudDogJ3NwYWNlLWJldHdlZW4nLCBmbGV4V3JhcDogJ3dyYXAnLCBnYXA6IDggfX0+XHJcbiAgICAgICAgICA8ZGl2IHN0eWxlPXt7IGRpc3BsYXk6ICdmbGV4JywgYWxpZ25JdGVtczogJ2NlbnRlcicsIGdhcDogMTAgfX0+XHJcbiAgICAgICAgICAgIDxEaXNjb25uZWN0T3V0bGluZWQgc3R5bGU9e3sgZm9udFNpemU6IDIyLCBjb2xvcjogV0gudGVhbCB9fSAvPlxyXG4gICAgICAgICAgICA8c3BhbiBzdHlsZT17eyBmb250U2l6ZTogMTUsIGZvbnRXZWlnaHQ6IDcwMCwgY29sb3I6IFdILnRleHQgfX0+UGFja2V0IExvc3MgU3RhdHVzPC9zcGFuPlxyXG4gICAgICAgICAgICA8TWV0cmljRXhwbGFpblBvcG92ZXIgdGV4dD17TUVUUklDX0VYUExBSU5bJ0FmZmVjdGVkIFNpdGVzJ119PlxyXG4gICAgICAgICAgICAgIDxUYWcgY29sb3I9XCJlcnJvclwiIHN0eWxlPXt7IGJvcmRlclJhZGl1czogMTIsIGZvbnRXZWlnaHQ6IDYwMCwgY3Vyc29yOiAncG9pbnRlcicgfX1cclxuICAgICAgICAgICAgICAgIG9uQ2xpY2s9e2UgPT4gb3BlbkRyaWxsZG93bihlLCAnYWxsJywgJ1NpdGVzIHdpdGggUGFja2V0IExvc3MnKX0+XHJcbiAgICAgICAgICAgICAgICB7Zm10KGRhdGEuYWZmZWN0ZWRfc2l0ZXMpfSBBZmZlY3RlZCBTaXRlc1xyXG4gICAgICAgICAgICAgIDwvVGFnPlxyXG4gICAgICAgICAgICA8L01ldHJpY0V4cGxhaW5Qb3BvdmVyPlxyXG4gICAgICAgICAgICA8TWV0cmljRXhwbGFpblBvcG92ZXIgdGV4dD17TUVUUklDX0VYUExBSU5bJ0RhdGEgR3JhbnVsYXJpdHknXX0+XHJcbiAgICAgICAgICAgICAgPFRhZyBjb2xvcj1cImN5YW5cIiBzdHlsZT17eyBib3JkZXJSYWRpdXM6IDEyLCBmb250V2VpZ2h0OiA2MDAgfX0+Ny1EYXkgSG91cmx5IMK3IFNEUiArIElQUkFOPC9UYWc+XHJcbiAgICAgICAgICAgIDwvTWV0cmljRXhwbGFpblBvcG92ZXI+XHJcbiAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICAgIDxkaXYgc3R5bGU9e3sgZGlzcGxheTogJ2ZsZXgnLCBhbGlnbkl0ZW1zOiAnY2VudGVyJywgZ2FwOiAxMiwgZm9udFNpemU6IDEyLCBjb2xvcjogV0gudGV4dERpbSB9fT5cclxuICAgICAgICAgICAgPENsb2NrQ2lyY2xlT3V0bGluZWQgLz5cclxuICAgICAgICAgICAgPHNwYW4+VXBkYXRlZDoge2RhdGEuZ2VuZXJhdGVkX2F0ID8gU3RyaW5nKGRhdGEuZ2VuZXJhdGVkX2F0KS5yZXBsYWNlKCdUJywgJyAnKS5zbGljZSgwLCAxOSkgOiAnTi9BJ308L3NwYW4+XHJcbiAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICA8L2Rpdj5cclxuICAgICAgPC9DYXJkPlxyXG5cclxuICAgICAgey8qIDIuIOaguOW/g+aMh+agh+WNoeeJhyAqL31cclxuICAgICAgPFJvdyBndXR0ZXI9e1sxMiwgMTJdfT5cclxuICAgICAgICA8Q29sIHNwYW49ezR9PlxyXG4gICAgICAgICAgPFN1bW1hcnlDYXJkIGljb249ezxFbnZpcm9ubWVudE91dGxpbmVkIC8+fSB2YWx1ZT17Zm10KGRhdGEudG90YWxfc2l0ZXMpfSBsYWJlbD1cIlRvdGFsIFNpdGVzXCIgY29sb3I9e1dILnRlYWx9XHJcbiAgICAgICAgICAgIGV4cGxhaW49e01FVFJJQ19FWFBMQUlOWydUb3RhbCBTaXRlcyddfVxyXG4gICAgICAgICAgICBvbkNsaWNrPXsoKSA9PiBvcGVuRHJpbGxkb3duKG51bGwsICdhbGwnLCAnQWxsIFNpdGVzJyl9IC8+XHJcbiAgICAgICAgPC9Db2w+XHJcbiAgICAgICAge1NUQVRVU19PUkRFUi5maWx0ZXIocyA9PiBzICE9PSAnTm8gUGFja2V0IGxvc3NbPDAuMV0nKS5tYXAoc3QgPT4gKFxyXG4gICAgICAgICAgPENvbCBzcGFuPXs0fSBrZXk9e3N0fT5cclxuICAgICAgICAgICAgPFN1bW1hcnlDYXJkXHJcbiAgICAgICAgICAgICAgaWNvbj17c3QgPT09ICdDcml0aWNhbFs+NV0nID8gPEFsZXJ0T3V0bGluZWQgLz4gOiBzdCA9PT0gJ01ham9yWzEtNV0nID8gPFdhcm5pbmdPdXRsaW5lZCAvPiA6IDxEYXNoYm9hcmRPdXRsaW5lZCAvPn1cclxuICAgICAgICAgICAgICB2YWx1ZT17Zm10KHNjW3N0XSB8fCAwKX0gbGFiZWw9e1NUQVRVU19TSE9SVFtzdF19IGNvbG9yPXtTVEFUVVNfQ09MT1JTW3N0XX1cclxuICAgICAgICAgICAgICBleHBsYWluPXtNRVRSSUNfRVhQTEFJTltTVEFUVVNfU0hPUlRbc3RdXX1cclxuICAgICAgICAgICAgICBvbkNsaWNrPXsoKSA9PiBvcGVuRHJpbGxkb3duKG51bGwsIHN0LCBzdCl9IC8+XHJcbiAgICAgICAgICA8L0NvbD5cclxuICAgICAgICApKX1cclxuICAgICAgICA8Q29sIHNwYW49ezR9PlxyXG4gICAgICAgICAgPFN1bW1hcnlDYXJkIGljb249ezxDaGVja0NpcmNsZU91dGxpbmVkIC8+fSB2YWx1ZT17Zm10KHNjWydObyBQYWNrZXQgbG9zc1s8MC4xXSddIHx8IDApfSBsYWJlbD1cIk5vIFBhY2tldCBsb3NzXCIgY29sb3I9e1NUQVRVU19DT0xPUlNbJ05vIFBhY2tldCBsb3NzWzwwLjFdJ119XHJcbiAgICAgICAgICAgIGV4cGxhaW49e01FVFJJQ19FWFBMQUlOWydObyBQYWNrZXQgbG9zcyddfVxyXG4gICAgICAgICAgICBvbkNsaWNrPXsoKSA9PiBvcGVuRHJpbGxkb3duKG51bGwsICdObyBQYWNrZXQgbG9zc1s8MC4xXScsICdObyBQYWNrZXQgbG9zc1s8MC4xXScpfSAvPlxyXG4gICAgICAgIDwvQ29sPlxyXG4gICAgICA8L1Jvdz5cclxuXHJcbiAgICAgIHsvKiAzLiDnirbmgIHliIbluIMgKyDmr4/ml6Xotovlir8gKyDljLrln5/liIbluIMgKi99XHJcbiAgICAgIDxTZWN0aW9uVGl0bGUgaWNvbj17PEJhckNoYXJ0T3V0bGluZWQgLz59IHRpdGxlPVwiTG9zcyBEaXN0cmlidXRpb25cIiBzdWI9XCJzdGF0dXMgwrcgZGFpbHkgdHJlbmQgwrcgcmVnaW9uIChjbGljayB0byBkcmlsbCBkb3duKVwiIC8+XHJcbiAgICAgIDxSb3cgZ3V0dGVyPXtbMTIsIDEyXX0+XHJcbiAgICAgICAgPENvbCBzcGFuPXs3fT5cclxuICAgICAgICAgIDxDYXJkIHNpemU9XCJzbWFsbFwiIHRpdGxlPXs8c3BhbiBzdHlsZT17eyBmb250U2l6ZTogMTMsIGZvbnRXZWlnaHQ6IDYwMCwgY29sb3I6IFdILnRleHQgfX0+U3RhdHVzIERpc3RyaWJ1dGlvbjwvc3Bhbj59IHN0eWxlPXtjYXJkV3JhcH0+XHJcbiAgICAgICAgICAgIDxSZWFjdEVDaGFydHMgb3B0aW9uPXtzdGF0dXNQaWVPcHRpb259IHN0eWxlPXt7IGhlaWdodDogQ0hBUlRfSEVJR0hUIH19IG9uRXZlbnRzPXt7IGNsaWNrOiBjaGFydENsaWNrKCdTdGF0dXMnKSB9fSAvPlxyXG4gICAgICAgICAgPC9DYXJkPlxyXG4gICAgICAgIDwvQ29sPlxyXG4gICAgICAgIDxDb2wgc3Bhbj17MTB9PlxyXG4gICAgICAgICAgPENhcmQgc2l6ZT1cInNtYWxsXCIgdGl0bGU9ezxzcGFuIHN0eWxlPXt7IGZvbnRTaXplOiAxMywgZm9udFdlaWdodDogNjAwLCBjb2xvcjogV0gudGV4dCB9fT5EYWlseSBUcmVuZCAoTGFzdCA3IERheXMpPC9zcGFuPn0gc3R5bGU9e2NhcmRXcmFwfT5cclxuICAgICAgICAgICAgPFJlYWN0RUNoYXJ0cyBvcHRpb249e3RyZW5kT3B0aW9ufSBzdHlsZT17eyBoZWlnaHQ6IENIQVJUX0hFSUdIVCB9fSAvPlxyXG4gICAgICAgICAgPC9DYXJkPlxyXG4gICAgICAgIDwvQ29sPlxyXG4gICAgICAgIDxDb2wgc3Bhbj17N30+XHJcbiAgICAgICAgICA8Q2FyZCBzaXplPVwic21hbGxcIiB0aXRsZT17PHNwYW4gc3R5bGU9e3sgZm9udFNpemU6IDEzLCBmb250V2VpZ2h0OiA2MDAsIGNvbG9yOiBXSC50ZXh0IH19PkFmZmVjdGVkIFNpdGVzIGJ5IFJlZ2lvbjwvc3Bhbj59IHN0eWxlPXtjYXJkV3JhcH0+XHJcbiAgICAgICAgICAgIDxSZWFjdEVDaGFydHMgb3B0aW9uPXtyZWdpb25PcHRpb259IHN0eWxlPXt7IGhlaWdodDogQ0hBUlRfSEVJR0hUIH19IC8+XHJcbiAgICAgICAgICA8L0NhcmQ+XHJcbiAgICAgICAgPC9Db2w+XHJcbiAgICAgIDwvUm93PlxyXG5cclxuICAgICAgey8qIDQuIFRvcCDnq5nngrnvvIjlnLDlm77lt7Lnp7voh7Plj7PkvqcgMS8zIOWIl++8iSAqL31cclxuICAgICAgPFNlY3Rpb25UaXRsZSBpY29uPXs8UGllQ2hhcnRPdXRsaW5lZCAvPn0gdGl0bGU9XCJUb3AgU2l0ZXNcIiBzdWI9XCJ3b3JzdCBzaXRlcyBieSBsYXN0LTEtZGF5IG1lZGlhbiBQTFwiIC8+XHJcbiAgICAgIDxDYXJkIHNpemU9XCJzbWFsbFwiIHRpdGxlPXs8c3BhbiBzdHlsZT17eyBmb250U2l6ZTogMTMsIGZvbnRXZWlnaHQ6IDYwMCwgY29sb3I6IFdILnRleHQgfX0+VG9wIFNpdGVzIChMYXN0LTEtZGF5IE1lZGlhbiBQTCk8L3NwYW4+fSBzdHlsZT17Y2FyZFdyYXB9PlxyXG4gICAgICAgIDxSZWFjdEVDaGFydHMgb3B0aW9uPXt0b3BTaXRlc09wdGlvbn0gc3R5bGU9e3sgaGVpZ2h0OiA1MjAgfX0gLz5cclxuICAgICAgPC9DYXJkPlxyXG4gICAgICA8L2Rpdj5cclxuXHJcbiAgICAgIHsvKiA9PT09PSDlj7PkvqcgMS8z77yaUGFja2V0IExvc3MgTWFwIOWNleeLrOWNoOaVtOWIl++8jOWPr+WbuuWumiA9PT09PSAqL31cclxuICAgICAgPGRpdiBzdHlsZT17eyBmbGV4OiAnMCAwIDMzLjMzMyUnLCB3aWR0aDogJzMzLjMzMyUnLCBwb3NpdGlvbjogJ3N0aWNreScsIHRvcDogMTIsIGFsaWduU2VsZjogJ2ZsZXgtc3RhcnQnIH19PlxyXG4gICAgICAgIDxDYXJkIHNpemU9XCJzbWFsbFwiIHN0eWxlPXt7IC4uLmNhcmRXcmFwLCBtYXJnaW5Cb3R0b206IDAgfX0gdGl0bGU9e1xyXG4gICAgICAgICAgPGRpdiBzdHlsZT17eyBkaXNwbGF5OiAnZmxleCcsIGFsaWduSXRlbXM6ICdjZW50ZXInLCBqdXN0aWZ5Q29udGVudDogJ3NwYWNlLWJldHdlZW4nIH19PlxyXG4gICAgICAgICAgICA8c3BhbiBzdHlsZT17eyBmb250U2l6ZTogMTMsIGZvbnRXZWlnaHQ6IDYwMCwgY29sb3I6IFdILnRleHQgfX0+UGFja2V0IExvc3MgTWFwICh7bWFwU2l0ZXMubGVuZ3RofSBzaXRlcyk8L3NwYW4+XHJcbiAgICAgICAgICAgIDxzcGFuIHN0eWxlPXt7IGZvbnRTaXplOiAxMSwgY29sb3I6IFdILnRleHRNdXRlZCwgZGlzcGxheTogJ2ZsZXgnLCBhbGlnbkl0ZW1zOiAnY2VudGVyJywgZ2FwOiA4IH19PlxyXG4gICAgICAgICAgICAgIDxCdXR0b24gc2l6ZT1cInNtYWxsXCIgdHlwZT17c2hvd1RvcG9sb2d5ID8gJ3ByaW1hcnknIDogJ2RlZmF1bHQnfVxyXG4gICAgICAgICAgICAgICAgaWNvbj17PEFwYXJ0bWVudE91dGxpbmVkIC8+fSBvbkNsaWNrPXsoKSA9PiBzZXRTaG93VG9wb2xvZ3kodiA9PiAhdil9XHJcbiAgICAgICAgICAgICAgICBzdHlsZT17eyBoZWlnaHQ6IDIyLCBmb250U2l6ZTogMTEsIGRpc3BsYXk6ICdpbmxpbmUtZmxleCcsIGFsaWduSXRlbXM6ICdjZW50ZXInLCBnYXA6IDQgfX0+XHJcbiAgICAgICAgICAgICAgICDmi5PmiZHmmL7npLpcclxuICAgICAgICAgICAgICA8L0J1dHRvbj5cclxuICAgICAgICAgICAgICBTaG93IE9LIHNpdGVzIDxTd2l0Y2ggc2l6ZT1cInNtYWxsXCIgY2hlY2tlZD17aW5jbHVkZU9rfSBvbkNoYW5nZT17c2V0SW5jbHVkZU9rfSAvPlxyXG4gICAgICAgICAgICA8L3NwYW4+XHJcbiAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICB9PlxyXG4gICAgICAgICAgPE1hcENvbnRhaW5lciBjZW50ZXI9e1s2LjQsIC05LjRdfSB6b29tPXs4fSBzdHlsZT17eyBoZWlnaHQ6ICdjYWxjKDEwMHZoIC0gMTgwcHgpJywgbWluSGVpZ2h0OiA0MjAsIHdpZHRoOiAnMTAwJScsIGJhY2tncm91bmQ6ICcjMGExOTI5JywgYm9yZGVyUmFkaXVzOiA4IH19IHNjcm9sbFdoZWVsWm9vbT5cclxuICAgICAgICAgICAgPFRpbGVMYXllciBhdHRyaWJ1dGlvbj0nJmNvcHk7IDxhIGhyZWY9XCJodHRwczovL3d3dy5vcGVuc3RyZWV0bWFwLm9yZy9jb3B5cmlnaHRcIj5PcGVuU3RyZWV0TWFwPC9hPicgdXJsPVwiaHR0cHM6Ly97c30udGlsZS5vcGVuc3RyZWV0bWFwLm9yZy97en0ve3h9L3t5fS5wbmdcIiAvPlxyXG4gICAgICAgICAgICB7Lyog5ouT5omR6L+e57q/77ya5aSN55SoIEdJUyBNYXAg55yf5a6e6ZO+6Lev77yM5oyJ5Lyg6L6T57G75Z6L552A6Imy77yITVcgLyBJUFJBTiDnrYnvvInjgIJcclxuICAgICAgICAgICAgICAgIOWFiOeZveiJsuaPj+i+uShjYXNpbmcp5aKe5by65a+55q+U77yM5YaN55S75b2p6Imy57q/77ybaHViIOmTvui3r+abtOeyl+OAgiAqL31cclxuICAgICAgICAgICAge3Nob3dUb3BvbG9neSAmJiB0b3BvbG9neS5lZGdlcy5tYXAoKGUsIGkpID0+IChcclxuICAgICAgICAgICAgICA8UG9seWxpbmUga2V5PXtgdG9wby1jLSR7aX1gfSBwb3NpdGlvbnM9e2UucG9zaXRpb25zfVxyXG4gICAgICAgICAgICAgICAgcGF0aE9wdGlvbnM9e3sgY29sb3I6ICcjZmZmZmZmJywgd2VpZ2h0OiBlLmlzSHViID8gNSA6IDMsIG9wYWNpdHk6IDAuMywgaW50ZXJhY3RpdmU6IGZhbHNlIH19IC8+XHJcbiAgICAgICAgICAgICkpfVxyXG4gICAgICAgICAgICB7c2hvd1RvcG9sb2d5ICYmIHRvcG9sb2d5LmVkZ2VzLm1hcCgoZSwgaSkgPT4gKFxyXG4gICAgICAgICAgICAgIDxQb2x5bGluZSBrZXk9e2B0b3BvLSR7aX1gfSBwb3NpdGlvbnM9e2UucG9zaXRpb25zfVxyXG4gICAgICAgICAgICAgICAgcGF0aE9wdGlvbnM9e3sgY29sb3I6IGUuY29sb3IsIHdlaWdodDogZS5pc0h1YiA/IDMgOiAxLjgsIG9wYWNpdHk6IDAuOSwgaW50ZXJhY3RpdmU6IGZhbHNlIH19IC8+XHJcbiAgICAgICAgICAgICkpfVxyXG4gICAgICAgICAgICB7dmlzaWJsZVNpdGVzLm1hcChzID0+IChcclxuICAgICAgICAgICAgICA8Q2lyY2xlTWFya2VyIGtleT17YCR7cy5zaXRlX25hbWV9fCR7cy5zaXRlX2NvZGV9YH0gY2VudGVyPXtbcy5sYXQsIHMubG5nXX1cclxuICAgICAgICAgICAgICAgIHJhZGl1cz17TWF0aC5taW4oMTIsIDUgKyBNYXRoLmxvZzFwKHMubGFzdF9kYXlfbWF4X3BsKSAqIDIpfVxyXG4gICAgICAgICAgICAgICAgZmlsbENvbG9yPXtTVEFUVVNfQ09MT1JTW3Muc3RhdHVzXSB8fCBXSC50ZWFsfSBjb2xvcj1cIiNmZmZcIiB3ZWlnaHQ9ezF9IGZpbGxPcGFjaXR5PXswLjg1fT5cclxuICAgICAgICAgICAgICAgIDxQb3B1cD5cclxuICAgICAgICAgICAgICAgICAgPGRpdiBzdHlsZT17eyBmb250U2l6ZTogMTIsIGxpbmVIZWlnaHQ6IDEuNiB9fT5cclxuICAgICAgICAgICAgICAgICAgICA8c3Ryb25nPntzLnNpdGVfbmFtZX08L3N0cm9uZz4ge3Muc2l0ZV9jb2RlICYmIGAoJHtzLnNpdGVfY29kZX0pYH08YnIgLz5cclxuICAgICAgICAgICAgICAgICAgICBTdGF0dXM6IDxzdHJvbmcgc3R5bGU9e3sgY29sb3I6IFNUQVRVU19DT0xPUlNbcy5zdGF0dXNdIH19PntTVEFUVVNfU0hPUlRbcy5zdGF0dXNdIHx8IHMuc3RhdHVzfTwvc3Ryb25nPjxiciAvPlxyXG4gICAgICAgICAgICAgICAgICAgIExhc3QtMS1kYXkgTWF4IFBMOiA8c3Ryb25nPntzLmxhc3RfZGF5X21heF9wbH0lPC9zdHJvbmc+PGJyIC8+XHJcbiAgICAgICAgICAgICAgICAgICAgN2QgVG90YWwgUEw6IHtzLnRvdGFsX3BsfSUgwrcgQWZmZWN0ZWQgSG91cnM6IHtzLmFmZmVjdGVkX2hvdXJzfTxiciAvPlxyXG4gICAgICAgICAgICAgICAgICAgIFJlZ2lvbjoge3MucmVnaW9uIHx8ICctJ30gLyB7cy5wcm92aW5jZV9jb3VudHkgfHwgJy0nfTxiciAvPlxyXG4gICAgICAgICAgICAgICAgICAgIEdhdGV3YXk6IHtzLmdhdGV3YXkgfHwgJy0nfSDCtyBOZXR3b3JrOiB7cy5uZXR3b3JrX3R5cGUgfHwgJy0nfVxyXG4gICAgICAgICAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICAgICAgICAgIDwvUG9wdXA+XHJcbiAgICAgICAgICAgICAgPC9DaXJjbGVNYXJrZXI+XHJcbiAgICAgICAgICAgICkpfVxyXG4gICAgICAgICAgPC9NYXBDb250YWluZXI+XHJcbiAgICAgICAgICB7c2hvd1RvcG9sb2d5ICYmIHRvcG9sb2d5LmdhdGV3YXlzLmxlbmd0aCA+IDAgJiYgKFxyXG4gICAgICAgICAgICA8ZGl2IHN0eWxlPXt7IGRpc3BsYXk6ICdmbGV4JywgZ2FwOiAxMCwgbWFyZ2luVG9wOiA2LCBtYXJnaW5Cb3R0b206IDIsIGZsZXhXcmFwOiAnd3JhcCcsIGFsaWduSXRlbXM6ICdjZW50ZXInIH19PlxyXG4gICAgICAgICAgICAgIDxzcGFuIHN0eWxlPXt7IGZvbnRTaXplOiAxMSwgY29sb3I6IFdILnRleHRNdXRlZCwgZm9udFdlaWdodDogNjAwIH19PlRvcG9sb2d5IChieSBUcmFuc3BvcnQpOjwvc3Bhbj5cclxuICAgICAgICAgICAgICB7dG9wb2xvZ3kuZ2F0ZXdheXMubWFwKGd3ID0+IChcclxuICAgICAgICAgICAgICAgIDxzcGFuIGtleT17Z3d9IHN0eWxlPXt7IGZvbnRTaXplOiAxMSwgY29sb3I6IFdILnRleHRNdXRlZCwgZGlzcGxheTogJ2ZsZXgnLCBhbGlnbkl0ZW1zOiAnY2VudGVyJywgZ2FwOiA0IH19PlxyXG4gICAgICAgICAgICAgICAgICA8c3BhbiBzdHlsZT17eyB3aWR0aDogMTQsIGhlaWdodDogNCwgYm9yZGVyUmFkaXVzOiAyLCBiYWNrZ3JvdW5kOiBnd0NvbG9yKGd3KSwgZGlzcGxheTogJ2lubGluZS1ibG9jaycgfX0gLz5cclxuICAgICAgICAgICAgICAgICAge2d3fVxyXG4gICAgICAgICAgICAgICAgPC9zcGFuPlxyXG4gICAgICAgICAgICAgICkpfVxyXG4gICAgICAgICAgICAgIDxzcGFuIHN0eWxlPXt7IGZvbnRTaXplOiAxMCwgY29sb3I6IFdILnRleHREaW0gfX0+77yI57q/5a694omIaHVi6ZO+6LevIC8g57uG57q/4omI5pmu6YCa6ZO+6Lev77yJPC9zcGFuPlxyXG4gICAgICAgICAgICA8L2Rpdj5cclxuICAgICAgICAgICl9XHJcbiAgICAgICAgICA8ZGl2IHN0eWxlPXt7IGRpc3BsYXk6ICdmbGV4JywgZ2FwOiAxMiwgbWFyZ2luVG9wOiA4LCBmbGV4V3JhcDogJ3dyYXAnIH19PlxyXG4gICAgICAgICAgICB7U1RBVFVTX09SREVSLm1hcChzdCA9PiB7XHJcbiAgICAgICAgICAgICAgY29uc3QgaGlkZGVuID0gaGlkZGVuU3RhdHVzZXMuaGFzKHN0KVxyXG4gICAgICAgICAgICAgIHJldHVybiAoXHJcbiAgICAgICAgICAgICAgICA8c3BhbiBrZXk9e3N0fSBvbkNsaWNrPXsoKSA9PiB0b2dnbGVTdGF0dXNWaXNpYmxlKHN0KX1cclxuICAgICAgICAgICAgICAgICAgdGl0bGU9e2hpZGRlbiA/ICdDbGljayB0byBzaG93IG9uIG1hcCcgOiAnQ2xpY2sgdG8gaGlkZSBvbiBtYXAnfVxyXG4gICAgICAgICAgICAgICAgICBzdHlsZT17e1xyXG4gICAgICAgICAgICAgICAgICAgIGZvbnRTaXplOiAxMSwgY3Vyc29yOiAncG9pbnRlcicsIHVzZXJTZWxlY3Q6ICdub25lJyxcclxuICAgICAgICAgICAgICAgICAgICBjb2xvcjogaGlkZGVuID8gV0gudGV4dERpbSA6IFdILnRleHRNdXRlZCxcclxuICAgICAgICAgICAgICAgICAgICBvcGFjaXR5OiBoaWRkZW4gPyAwLjQ1IDogMSxcclxuICAgICAgICAgICAgICAgICAgICB0ZXh0RGVjb3JhdGlvbjogaGlkZGVuID8gJ2xpbmUtdGhyb3VnaCcgOiAnbm9uZScsXHJcbiAgICAgICAgICAgICAgICAgICAgZGlzcGxheTogJ2ZsZXgnLCBhbGlnbkl0ZW1zOiAnY2VudGVyJywgZ2FwOiA0LFxyXG4gICAgICAgICAgICAgICAgICB9fT5cclxuICAgICAgICAgICAgICAgICAgPHNwYW4gc3R5bGU9e3sgd2lkdGg6IDEwLCBoZWlnaHQ6IDEwLCBib3JkZXJSYWRpdXM6ICc1MCUnLCBiYWNrZ3JvdW5kOiBTVEFUVVNfQ09MT1JTW3N0XSwgZGlzcGxheTogJ2lubGluZS1ibG9jaycsIG9wYWNpdHk6IGhpZGRlbiA/IDAuMyA6IDEgfX0gLz5cclxuICAgICAgICAgICAgICAgICAge1NUQVRVU19TSE9SVFtzdF19XHJcbiAgICAgICAgICAgICAgICA8L3NwYW4+XHJcbiAgICAgICAgICAgICAgKVxyXG4gICAgICAgICAgICB9KX1cclxuICAgICAgICAgIDwvZGl2PlxyXG4gICAgICAgIDwvQ2FyZD5cclxuICAgICAgPC9kaXY+XHJcblxyXG4gICAgICB7Lyog5LiL6ZK75by556qXICovfVxyXG4gICAgICA8RHJhZ2dhYmxlQ2xpY2tNb2RhbFxyXG4gICAgICAgIG9wZW49e2RyaWxsT3Blbn1cclxuICAgICAgICBhbmNob3I9e2RyaWxsQW5jaG9yfVxyXG4gICAgICAgIGRhcmtcclxuICAgICAgICBvbkNsb3NlPXsoKSA9PiBzZXREcmlsbE9wZW4oZmFsc2UpfVxyXG4gICAgICAgIHRpdGxlPXs8c3BhbiBzdHlsZT17eyBjb2xvcjogV0gudGV4dCB9fT57ZHJpbGxUaXRsZX0gPFRhZyBjb2xvcj1cImN5YW5cIiBzdHlsZT17eyBib3JkZXJSYWRpdXM6IDEwIH19PntmaWx0ZXJlZERyaWxsRGF0YS5sZW5ndGh9IHJlY29yZHM8L1RhZz48L3NwYW4+fVxyXG4gICAgICA+XHJcbiAgICAgICAgPGRpdiBzdHlsZT17eyBkaXNwbGF5OiAnZmxleCcsIGp1c3RpZnlDb250ZW50OiAnc3BhY2UtYmV0d2VlbicsIG1hcmdpbkJvdHRvbTogMTIgfX0+XHJcbiAgICAgICAgICA8SW5wdXQgcHJlZml4PXs8U2VhcmNoT3V0bGluZWQgLz59IHBsYWNlaG9sZGVyPVwiU2VhcmNoIHNpdGUgLyBjb2RlIC8gcmVnaW9uLi4uXCIgYWxsb3dDbGVhciBzaXplPVwibWlkZGxlXCJcclxuICAgICAgICAgICAgc3R5bGU9e3sgd2lkdGg6IDM1MCB9fSB2YWx1ZT17ZHJpbGxTZWFyY2h9IG9uQ2hhbmdlPXtlID0+IHNldERyaWxsU2VhcmNoKGUudGFyZ2V0LnZhbHVlKX0gLz5cclxuICAgICAgICAgIDxCdXR0b24gdHlwZT1cInByaW1hcnlcIiBpY29uPXs8RG93bmxvYWRPdXRsaW5lZCAvPn0gb25DbGljaz17ZXhwb3J0VG9FeGNlbH0gZGlzYWJsZWQ9eyFmaWx0ZXJlZERyaWxsRGF0YS5sZW5ndGh9PlxyXG4gICAgICAgICAgICBFeHBvcnQgRXhjZWxcclxuICAgICAgICAgIDwvQnV0dG9uPlxyXG4gICAgICAgIDwvZGl2PlxyXG4gICAgICAgIHtkcmlsbExvYWRpbmcgPyAoXHJcbiAgICAgICAgICA8U3BpbiBzdHlsZT17eyBkaXNwbGF5OiAnYmxvY2snLCBtYXJnaW46ICc2MHB4IGF1dG8nIH19IC8+XHJcbiAgICAgICAgKSA6IChcclxuICAgICAgICAgIDxUYWJsZSBkYXRhU291cmNlPXtmaWx0ZXJlZERyaWxsRGF0YX0gY29sdW1ucz17ZHJpbGxDb2x1bW5zfSBzaXplPVwic21hbGxcIlxyXG4gICAgICAgICAgICByb3dLZXk9eyhyOiBhbnkpID0+IHIuU2l0ZV9OYW1lfVxyXG4gICAgICAgICAgICBwYWdpbmF0aW9uPXt7IHBhZ2VTaXplOiAxNSwgc2l6ZTogJ3NtYWxsJywgc2hvd1RvdGFsOiAodG90YWw6IG51bWJlcikgPT4gYCR7dG90YWx9IGl0ZW1zYCB9fVxyXG4gICAgICAgICAgICBzY3JvbGw9e3sgeDogJ21heC1jb250ZW50JyB9fSAvPlxyXG4gICAgICAgICl9XHJcbiAgICAgIDwvRHJhZ2dhYmxlQ2xpY2tNb2RhbD5cclxuICAgIDwvZGl2PlxyXG4gIClcclxufVxyXG4iXX0=