import React from 'react';
import {AbsoluteFill, Img, Sequence, interpolate, useCurrentFrame, staticFile} from 'remotion';
import {Scenario} from '../data/scenarios';
import {DeviceFrame} from '../components/DeviceFrame';
import {CursorPointer} from '../components/CursorPointer';
import {ScreenHighlight} from '../components/ScreenHighlight';
import {CountUp} from '../components/CountUp';
import {MockScreen} from '../components/MockScreen';
import {CharacterStage} from '../components/CharacterStage';

const RaisePhase: React.FC<{scenario: Scenario}> = ({scenario}) => {
	const frame = useCurrentFrame();
	const armRaise = interpolate(frame, [0, scenario.raiseFrames - 6], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const scale = interpolate(frame, [0, scenario.raiseFrames], [1, 1.12], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<CharacterStage
			armRaise={armRaise}
			mood="neutral"
			accentColor={scenario.accentColor}
			scale={scale}
		/>
	);
};

const ResultPhase: React.FC<{scenario: Scenario}> = ({scenario}) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(frame, [0, 12], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<CharacterStage
			armRaise={0.75}
			mood="happy"
			accentColor={scenario.accentColor}
			caption={scenario.resultLine}
		>
			{scenario.resultNumber && (
				<div style={{opacity, textAlign: 'center', marginTop: 12}}>
					<span style={{fontSize: 56, fontWeight: 800, color: '#7CFFB2'}}>
						<CountUp
							from={scenario.resultNumber.from}
							to={scenario.resultNumber.to}
							startFrame={0}
							durationInFrames={20}
						/>
						{scenario.resultNumber.suffix}
					</span>
				</div>
			)}
		</CharacterStage>
	);
};

export const ScenarioScene: React.FC<{scenario: Scenario}> = ({scenario}) => {
	const {painFrames, raiseFrames, toolFrames, resultFrames} = scenario;

	return (
		<AbsoluteFill style={{background: '#12172c'}}>
			<Sequence from={0} durationInFrames={painFrames}>
				<CharacterStage
					armRaise={0}
					mood="worried"
					entrance
					accentColor={scenario.accentColor}
					caption={scenario.painLine}
				/>
			</Sequence>

			<Sequence from={painFrames} durationInFrames={raiseFrames}>
				<RaisePhase scenario={scenario} />
			</Sequence>

			<Sequence from={painFrames + raiseFrames} durationInFrames={toolFrames}>
				<AbsoluteFill style={{background: '#f0f1f5'}}>
					<div
						style={{
							position: 'absolute',
							top: 28,
							left: 0,
							right: 0,
							textAlign: 'center',
							color: '#1a1a2e',
							fontSize: 22,
							fontWeight: 700,
							zIndex: 20,
						}}
					>
						{scenario.toolName}
					</div>
					<DeviceFrame variant={scenario.deviceVariant}>
						<div style={{position: 'relative', width: '100%', height: '100%'}}>
							{scenario.screenshotSrc ? (
								<Img
									src={staticFile(scenario.screenshotSrc)}
									style={{width: '100%', height: '100%', objectFit: 'cover'}}
								/>
							) : scenario.mockScreen ? (
								<MockScreen title={scenario.mockScreen.title} rows={scenario.mockScreen.rows} />
							) : null}

							{scenario.highlight && (
								<ScreenHighlight
									xPercent={scenario.highlight.xPercent}
									yPercent={scenario.highlight.yPercent}
									widthPercent={scenario.highlight.widthPercent}
									heightPercent={scenario.highlight.heightPercent}
									label={scenario.highlight.label}
									appearFrame={25}
									disappearFrame={toolFrames - 20}
								/>
							)}

							<CursorPointer waypoints={scenario.cursorWaypoints} />
						</div>
					</DeviceFrame>
				</AbsoluteFill>
			</Sequence>

			<Sequence from={painFrames + raiseFrames + toolFrames} durationInFrames={resultFrames}>
				<ResultPhase scenario={scenario} />
			</Sequence>
		</AbsoluteFill>
	);
};
