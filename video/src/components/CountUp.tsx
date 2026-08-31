import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';

type CountUpProps = {
	from: number;
	to: number;
	startFrame: number;
	durationInFrames: number;
	formatter?: (value: number) => string;
	style?: React.CSSProperties;
};

export const CountUp: React.FC<CountUpProps> = ({
	from,
	to,
	startFrame,
	durationInFrames,
	formatter,
	style,
}) => {
	const frame = useCurrentFrame();
	const value = interpolate(frame, [startFrame, startFrame + durationInFrames], [from, to], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const rounded = Math.round(value);

	return <span style={style}>{formatter ? formatter(rounded) : rounded}</span>;
};
