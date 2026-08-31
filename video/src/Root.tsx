import React from 'react';
import {Composition} from 'remotion';
import {ShortVideo, getTotalDurationInFrames} from './ShortVideo';

export const Root: React.FC = () => {
	return (
		<>
			<Composition
				id="ShortVideo"
				component={ShortVideo}
				durationInFrames={getTotalDurationInFrames()}
				fps={30}
				width={1080}
				height={1920}
			/>
		</>
	);
};
