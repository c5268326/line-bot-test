import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';

export type Mood = 'worried' | 'neutral' | 'happy';

type CharacterProps = {
	/** 0 = 手臂自然下垂，1 = 手機抬到胸前操作位置 */
	armRaise: number;
	mood: Mood;
	/** 第一次出場時做進場滑入+淡入，之後的鏡頭切回就不要再重播 */
	entrance?: boolean;
	accentColor?: string;
};

const SKIN = '#f0c39a';
const HAIR = '#3b2a20';
const BLAZER = '#2d3a55';
const SHIRT = '#eef1f6';

export const Character: React.FC<CharacterProps> = ({
	armRaise,
	mood,
	entrance = false,
	accentColor = '#2fb6a5',
}) => {
	const frame = useCurrentFrame();

	const breathe = Math.sin(frame * 0.12) * 2;

	const entranceProgress = entrance
		? interpolate(frame, [0, 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
		: 1;
	const entranceY = interpolate(entranceProgress, [0, 1], [50, 0]);

	const shoulderX = 380;
	const shoulderY = 235;
	const restAngle = 0;
	const raisedAngle = 100;
	const armAngle = interpolate(armRaise, [0, 1], [restAngle, raisedAngle]);

	// 手臂抬起時頭稍微低頭看手機
	const headTilt = interpolate(armRaise, [0, 1], [0, 6]);

	const eyebrowY = mood === 'worried' ? -4 : 0;
	const eyebrowAngle = mood === 'worried' ? 12 : mood === 'happy' ? -6 : 0;

	return (
		<g
			transform={`translate(0, ${entranceY + breathe})`}
			opacity={entranceProgress}
		>
			{/* 左臂（放鬆自然垂放） */}
			<rect x={104} y={230} width={32} height={140} rx={16} fill={BLAZER} />
			<circle cx={120} cy={372} r={19} fill={SKIN} />

			{/* 身體 */}
			<rect x={130} y={190} width={240} height={330} rx={60} fill={BLAZER} />
			<path d="M 175 210 L 200 260 L 225 210 Z" fill={SHIRT} />
			<rect x={196} y={210} width={8} height={70} fill={accentColor} />

			{/* 頭 */}
			<g transform={`rotate(${headTilt} 200 130)`}>
				<circle cx={200} cy={130} r={72} fill={SKIN} />
				<path
					d="M 128 120 Q 130 40 200 40 Q 270 40 272 120 Q 272 70 200 65 Q 128 70 128 120 Z"
					fill={HAIR}
				/>
				{/* 眉毛 */}
				<rect
					x={155}
					y={112 + eyebrowY}
					width={30}
					height={7}
					rx={3.5}
					fill={HAIR}
					transform={`rotate(${eyebrowAngle} 170 115)`}
				/>
				<rect
					x={215}
					y={112 + eyebrowY}
					width={30}
					height={7}
					rx={3.5}
					fill={HAIR}
					transform={`rotate(${-eyebrowAngle} 230 115)`}
				/>
				{/* 眼睛 */}
				<circle cx={172} cy={132} r={7} fill="#2a2a2a" />
				<circle cx={228} cy={132} r={7} fill="#2a2a2a" />
				{/* 嘴巴 */}
				{mood === 'happy' ? (
					<path
						d="M 172 168 Q 200 196 228 168"
						stroke="#8a4a3a"
						strokeWidth={7}
						strokeLinecap="round"
						fill="none"
					/>
				) : mood === 'worried' ? (
					<path
						d="M 178 176 Q 200 166 222 176"
						stroke="#8a4a3a"
						strokeWidth={6}
						strokeLinecap="round"
						fill="none"
					/>
				) : (
					<path
						d="M 178 172 Q 200 182 222 172"
						stroke="#8a4a3a"
						strokeWidth={6}
						strokeLinecap="round"
						fill="none"
					/>
				)}
			</g>

			{/* 右臂（拿手機，操作數位工具的那隻） */}
			<g transform={`rotate(${armAngle} ${shoulderX} ${shoulderY})`}>
				<rect x={shoulderX - 17} y={shoulderY} width={34} height={150} rx={17} fill={BLAZER} />
				<circle cx={shoulderX} cy={shoulderY + 150} r={20} fill={SKIN} />
				<g transform={`translate(${shoulderX - 22}, ${shoulderY + 128}) rotate(${-armAngle} 22 39)`}>
					<rect width={44} height={78} rx={9} fill="#151515" />
					<rect x={4} y={6} width={36} height={66} rx={4} fill="#eaf2ff" />
					<rect x={9} y={13} width={26} height={7} rx={2} fill={accentColor} opacity={0.85} />
					<rect x={9} y={26} width={26} height={5} rx={2} fill="#c7d3e6" />
					<rect x={9} y={35} width={18} height={5} rx={2} fill="#c7d3e6" />
				</g>
			</g>
		</g>
	);
};
