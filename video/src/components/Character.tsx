import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';

export type Mood = 'worried' | 'neutral' | 'happy';

type CharacterProps = {
	/** 0 = 手臂自然下垂，1 = 手機抬到胸前操作位置 */
	armRaise: number;
	mood: Mood;
	/** 第一次出場時做進場滑入+淡入，之後的鏡頭切回就不要再重播 */
	entrance?: boolean;
	/** 配音播放中，嘴巴會一開一合 */
	talking?: boolean;
	accentColor?: string;
};

const SKIN = '#ffd7ae';
const HAIR = '#3b2a20';
const SHIRT = '#fdfdfd';
const BLUSH = '#ff9d9d';

export const Character: React.FC<CharacterProps> = ({
	armRaise,
	mood,
	entrance = false,
	talking = false,
	accentColor = '#2fb6a5',
}) => {
	const frame = useCurrentFrame();

	// 待機彈跳＋輕微搖擺，讓角色不是死板站著
	const bounce = Math.sin(frame * 0.16) * 7;
	const sway = Math.sin(frame * 0.1) * 2;

	const entranceProgress = entrance
		? interpolate(frame, [0, 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
		: 1;
	const entranceY = interpolate(entranceProgress, [0, 1], [60, 0]);
	const entranceScale = interpolate(entranceProgress, [0, 1], [0.85, 1]);

	const shoulderX = 345;
	const shoulderY = 300;
	const restAngle = 0;
	const raisedAngle = 100;
	const armAngle = interpolate(armRaise, [0, 1], [restAngle, raisedAngle]);

	// 手臂抬起時頭稍微低頭看手機
	const headTilt = interpolate(armRaise, [0, 1], [0, 7]);

	// 眨眼：每 3 秒快速眨一下
	const blinkPhase = frame % 90;
	const blinking = blinkPhase < 6;
	const eyeScaleY = blinking ? 0.12 : 1;

	// 講話時嘴巴一開一合
	const talkOpen = talking && Math.floor(frame / 4) % 2 === 0;

	const eyebrowLift = mood === 'worried' ? -3 : mood === 'happy' ? 5 : 0;
	const eyebrowAngle = mood === 'worried' ? 16 : mood === 'happy' ? -10 : 2;

	return (
		<g
			transform={`translate(0, ${entranceY + bounce}) rotate(${sway} 200 400) scale(${entranceScale})`}
			opacity={entranceProgress}
			style={{transformOrigin: '200px 300px'}}
		>
			{/* 左臂（放鬆自然垂放，會隨彈跳輕輕擺動） */}
			<g transform={`rotate(${sway * -1.4} 52 300)`}>
				<rect x={34} y={300} width={36} height={160} rx={18} fill={accentColor} />
				<circle cx={52} cy={460} r={22} fill={SKIN} />
			</g>

			{/* 身體：肩膀寬、腰部收，比較有造型而不是一個方塊 */}
			<path
				d="M 70 340
				   Q 75 262 140 262
				   L 260 262
				   Q 325 262 330 340
				   Q 336 440 278 560
				   L 122 560
				   Q 64 440 70 340
				   Z"
				fill={accentColor}
			/>
			<path d="M 172 268 L 200 320 L 228 268 Z" fill={SHIRT} />
			<rect x={195} y={268} width={10} height={90} fill="#ffffff" opacity={0.55} />

			{/* 頭（比例放大，可愛一點） */}
			<g transform={`rotate(${headTilt} 200 160)`}>
				<circle cx={200} cy={160} r={100} fill={SKIN} />

				{/* 腮紅 */}
				<ellipse cx={140} cy={195} rx={16} ry={9} fill={BLUSH} opacity={0.55} />
				<ellipse cx={260} cy={195} rx={16} ry={9} fill={BLUSH} opacity={0.55} />

				{/* 頭髮 */}
				<path
					d="M 104 150 Q 100 48 200 44 Q 300 48 296 150
					   Q 300 84 200 76 Q 100 84 104 150 Z"
					fill={HAIR}
				/>
				<path d="M 100 140 Q 92 110 118 90" stroke={HAIR} strokeWidth={14} strokeLinecap="round" fill="none" />
				<path d="M 300 140 Q 308 110 282 90" stroke={HAIR} strokeWidth={14} strokeLinecap="round" fill="none" />

				{/* 眉毛 */}
				<rect
					x={148}
					y={132 + eyebrowLift}
					width={38}
					height={9}
					rx={4.5}
					fill={HAIR}
					transform={`rotate(${eyebrowAngle} 167 136)`}
				/>
				<rect
					x={214}
					y={132 + eyebrowLift}
					width={38}
					height={9}
					rx={4.5}
					fill={HAIR}
					transform={`rotate(${-eyebrowAngle} 233 136)`}
				/>

				{/* 眼睛（含眨眼、亮點） */}
				<g transform={`translate(167,158) scale(1,${eyeScaleY})`}>
					<circle r={13} fill="#2a2a2a" />
					<circle cx={-4} cy={-4} r={4} fill="#ffffff" />
				</g>
				<g transform={`translate(233,158) scale(1,${eyeScaleY})`}>
					<circle r={13} fill="#2a2a2a" />
					<circle cx={-4} cy={-4} r={4} fill="#ffffff" />
				</g>

				{/* 嘴巴（含說話開合） */}
				{talkOpen ? (
					<ellipse cx={200} cy={214} rx={16} ry={13} fill="#8a4a3a" />
				) : mood === 'happy' ? (
					<path
						d="M 168 206 Q 200 240 232 206"
						stroke="#8a4a3a"
						strokeWidth={9}
						strokeLinecap="round"
						fill="none"
					/>
				) : mood === 'worried' ? (
					<path
						d="M 176 216 Q 200 204 224 216"
						stroke="#8a4a3a"
						strokeWidth={8}
						strokeLinecap="round"
						fill="none"
					/>
				) : (
					<path
						d="M 176 210 Q 200 222 224 210"
						stroke="#8a4a3a"
						strokeWidth={8}
						strokeLinecap="round"
						fill="none"
					/>
				)}
			</g>

			{/* 右臂（拿手機，操作數位工具的那隻） */}
			<g transform={`rotate(${armAngle} ${shoulderX} ${shoulderY})`}>
				<rect x={shoulderX - 18} y={shoulderY} width={36} height={170} rx={18} fill={accentColor} />
				<circle cx={shoulderX} cy={shoulderY + 170} r={23} fill={SKIN} />
				<g
					transform={`translate(${shoulderX - 24}, ${shoulderY + 146}) rotate(${-armAngle} 24 42)`}
				>
					<rect width={48} height={84} rx={10} fill="#151515" />
					<rect x={4} y={6} width={40} height={72} rx={5} fill="#eaf2ff" />
					<rect x={10} y={14} width={28} height={8} rx={2} fill={accentColor} opacity={0.85} />
					<rect x={10} y={28} width={28} height={5} rx={2} fill="#c7d3e6" />
					<rect x={10} y={38} width={20} height={5} rx={2} fill="#c7d3e6" />
				</g>
			</g>
		</g>
	);
};
