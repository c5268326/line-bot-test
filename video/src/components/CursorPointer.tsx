import React from 'react';
import {interpolate, useCurrentFrame, Easing} from 'remotion';

export type CursorWaypoint = {
	frame: number;
	xPercent: number;
	yPercent: number;
	click?: boolean;
};

type CursorPointerProps = {
	waypoints: CursorWaypoint[];
};

/**
 * Animates a cursor icon through a list of {frame, xPercent, yPercent} waypoints
 * (percentages are relative to the parent container) and shows a click ripple
 * on waypoints flagged `click: true`.
 */
export const CursorPointer: React.FC<CursorPointerProps> = ({waypoints}) => {
	const frame = useCurrentFrame();

	if (waypoints.length === 0) {
		return null;
	}

	const frames = waypoints.map((w) => w.frame);
	const xs = waypoints.map((w) => w.xPercent);
	const ys = waypoints.map((w) => w.yPercent);

	const x = interpolate(frame, frames, xs, {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.inOut(Easing.ease),
	});
	const y = interpolate(frame, frames, ys, {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.inOut(Easing.ease),
	});

	const nearestClick = waypoints.find(
		(w) => w.click && Math.abs(w.frame - frame) < 12
	);
	const clickProgress = nearestClick
		? interpolate(frame, [nearestClick.frame, nearestClick.frame + 12], [0, 1], {
				extrapolateLeft: 'clamp',
				extrapolateRight: 'clamp',
			})
		: null;

	return (
		<div
			style={{
				position: 'absolute',
				left: `${x}%`,
				top: `${y}%`,
				transform: 'translate(-10%, -10%)',
				zIndex: 10,
				pointerEvents: 'none',
			}}
		>
			{clickProgress !== null && (
				<div
					style={{
						position: 'absolute',
						left: 10,
						top: 10,
						width: 36,
						height: 36,
						borderRadius: '50%',
						border: '3px solid rgba(255,90,90,0.8)',
						transform: `translate(-50%, -50%) scale(${1 + clickProgress * 1.6})`,
						opacity: 1 - clickProgress,
					}}
				/>
			)}
			<svg width="34" height="34" viewBox="0 0 24 24" fill="none">
				<path
					d="M4 2 L4 20 L9 15.5 L12.5 22 L15.5 20.5 L12 14 L19 14 Z"
					fill="white"
					stroke="black"
					strokeWidth="1.4"
					strokeLinejoin="round"
				/>
			</svg>
		</div>
	);
};
