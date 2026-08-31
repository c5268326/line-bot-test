import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';

type ScreenHighlightProps = {
	xPercent: number;
	yPercent: number;
	widthPercent: number;
	heightPercent: number;
	label?: string;
	appearFrame: number;
	disappearFrame: number;
};

export const ScreenHighlight: React.FC<ScreenHighlightProps> = ({
	xPercent,
	yPercent,
	widthPercent,
	heightPercent,
	label,
	appearFrame,
	disappearFrame,
}) => {
	const frame = useCurrentFrame();

	const opacity = interpolate(
		frame,
		[appearFrame, appearFrame + 10, disappearFrame - 10, disappearFrame],
		[0, 1, 1, 0],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);
	const scale = interpolate(frame, [appearFrame, appearFrame + 10], [0.92, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	if (opacity <= 0) {
		return null;
	}

	return (
		<div
			style={{
				position: 'absolute',
				left: `${xPercent}%`,
				top: `${yPercent}%`,
				width: `${widthPercent}%`,
				height: `${heightPercent}%`,
				border: '3px solid #ff5a5a',
				borderRadius: 10,
				boxShadow: '0 0 0 4000px rgba(0,0,0,0.15)',
				opacity,
				transform: `scale(${scale})`,
				transformOrigin: 'center',
				zIndex: 5,
			}}
		>
			{label && (
				<div
					style={{
						position: 'absolute',
						bottom: '100%',
						left: 0,
						marginBottom: 8,
						background: '#ff5a5a',
						color: 'white',
						fontSize: 16,
						fontWeight: 600,
						padding: '4px 10px',
						borderRadius: 6,
						whiteSpace: 'nowrap',
					}}
				>
					{label}
				</div>
			)}
		</div>
	);
};
