import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {Scenario, scenarios} from './data/scenarios';
import {ScenarioScene} from './scenarios/ScenarioScene';

export const TRANSITION_FRAMES = 20;

export const getSceneDuration = (s: Scenario) =>
	s.painFrames + s.raiseFrames + s.toolFrames + s.resultFrames;

export const getTotalDurationInFrames = () => {
	const sum = scenarios.reduce((acc, s) => acc + getSceneDuration(s), 0);
	return sum - TRANSITION_FRAMES * Math.max(scenarios.length - 1, 0);
};

export const ShortVideo: React.FC = () => {
	const children: React.ReactNode[] = [];

	scenarios.forEach((scenario, index) => {
		children.push(
			<TransitionSeries.Sequence
				key={`scene-${scenario.id}`}
				durationInFrames={getSceneDuration(scenario)}
			>
				<ScenarioScene scenario={scenario} />
			</TransitionSeries.Sequence>
		);

		if (index < scenarios.length - 1) {
			children.push(
				<TransitionSeries.Transition
					key={`transition-${scenario.id}`}
					presentation={fade()}
					timing={linearTiming({durationInFrames: TRANSITION_FRAMES})}
				/>
			);
		}
	});

	return (
		<AbsoluteFill style={{background: 'black'}}>
			<Audio src={staticFile('audio/music/bgm-loop.mp3')} loop volume={0.22} />
			<TransitionSeries>{children}</TransitionSeries>
		</AbsoluteFill>
	);
};
