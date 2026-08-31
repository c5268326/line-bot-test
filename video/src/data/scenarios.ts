import {CursorWaypoint} from '../components/CursorPointer';

export type Scenario = {
	id: string;
	/** 業務員遇到的痛點口白/字幕 */
	painLine: string;
	/** 工具名稱，顯示在畫面上方小標籤 */
	toolName: string;
	deviceVariant: 'phone' | 'browser';
	/**
	 * 真實截圖路徑（相對於 public/，例如 "screenshots/line-report.png"）。
	 * 留空則使用 MockScreen 佔位畫面，之後有截圖再填入即可。
	 */
	screenshotSrc?: string;
	mockScreen?: {
		title: string;
		rows: {label: string; value: string}[];
	};
	highlight?: {
		xPercent: number;
		yPercent: number;
		widthPercent: number;
		heightPercent: number;
		label?: string;
	};
	cursorWaypoints: CursorWaypoint[];
	/** 效益／結果口白 */
	resultLine: string;
	resultNumber?: {from: number; to: number; suffix: string};
	/** 各階段時長（frame，30fps） */
	painFrames: number;
	/** 角色抬手打開工具的過場時長 */
	raiseFrames: number;
	toolFrames: number;
	resultFrames: number;
	accentColor?: string;
};

export const FPS = 30;

export const scenarios: Scenario[] = [
	{
		id: 'query-performance',
		painLine: '拜訪客戶前，臨時要查最新業績…上系統又要等 IT 開權限？',
		toolName: 'LINE 業績查詢機器人',
		deviceVariant: 'phone',
		mockScreen: {
			title: '📊 最新業績查詢',
			rows: [
				{label: '實收保費', value: '182萬'},
				{label: '實收達成率', value: '96%'},
				{label: '加權保費', value: '210萬'},
			],
		},
		highlight: {
			xPercent: 6,
			yPercent: 6,
			widthPercent: 88,
			heightPercent: 25,
			label: '即時數字',
		},
		cursorWaypoints: [
			{frame: 0, xPercent: 80, yPercent: 85},
			{frame: 20, xPercent: 50, yPercent: 18, click: true},
			{frame: 40, xPercent: 50, yPercent: 15},
		],
		resultLine: '3 秒查完，不用再等總部回覆',
		resultNumber: {from: 0, to: 3, suffix: ' 秒'},
		painFrames: 70,
		raiseFrames: 30,
		toolFrames: 210,
		resultFrames: 70,
		accentColor: '#2fb6a5',
	},
	{
		id: 'region-report',
		painLine: '客戶問起「你們這區做得怎樣？」，手邊完全沒資料可以秀…',
		toolName: 'LINE 分區報表圖片',
		deviceVariant: 'phone',
		mockScreen: {
			title: '📍 桃竹苗區報表',
			rows: [
				{label: '達成率', value: '104%'},
				{label: '排名', value: '全國第 2'},
			],
		},
		highlight: {
			xPercent: 6,
			yPercent: 6,
			widthPercent: 88,
			heightPercent: 20,
			label: '一秒有圖',
		},
		cursorWaypoints: [
			{frame: 0, xPercent: 80, yPercent: 85},
			{frame: 20, xPercent: 50, yPercent: 15, click: true},
		],
		resultLine: '客戶當場就能看到最新戰績',
		painFrames: 70,
		raiseFrames: 30,
		toolFrames: 180,
		resultFrames: 70,
		accentColor: '#e08a3c',
	},
];
