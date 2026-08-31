import React from 'react';
import {AbsoluteFill, Img, Sequence, interpolate, useCurrentFrame, staticFile} from 'remotion';
import {Scenario} from '../data/scenarios';
import {DeviceFrame} from '../components/DeviceFrame';
import {CursorPointer} from '../components/CursorPointer';
import {ScreenHighlight} from '../components/ScreenHighlight';
import {CountUp} from '../components/CountUp';
import {MockScreen} from '../components/MockScreen';

const FadeText: React.FC<{
	children: React.ReactNode;
	durationInFrames: number;
	style?: React.CSSProperties;
}> = ({children, durationInFrames, style}) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(
		frame,
		[0, 12, durationInFrames - 12, durationInFrames],
		[0, 1, 1, 0],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);
	const translateY = interpolate(frame, [0, 12], [16, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill
			style={{
				alignItems: 'center',
				justifyContent: 'center',
				padding: '0 90px',
				textAlign: 'center',
			}}
		>
			<div style={{opacity, transform: `translateY(${translateY}px)`, ...style}}>
				{children}
			</div>
		</AbsoluteFill>
	);
};

export const ScenarioScene: React.FC<{scenario: Scenario}> = ({scenario}) => {
	const {painFrames, toolFrames, resultFrames} = scenario;

	return (
		<AbsoluteFill style={{background: '#0f1226'}}>
			<Sequence from={0} durationInFrames={painFrames}>
				<FadeText durationInFrames={painFrames}>
					<div style={{fontSize: 40, fontWeight: 700, color: 'white', lineHeight: 1.5}}>
						{scenario.painLine}
					</div>
				</FadeText>
			</Sequence>

			<Sequence from={painFrames} durationInFrames={toolFrames}>
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

			<Sequence from={painFrames + toolFrames} durationInFrames={resultFrames}>
				<FadeText durationInFrames={resultFrames}>
					<div style={{fontSize: 44, fontWeight: 800, color: '#7CFFB2'}}>
						{scenario.resultNumber ? (
							<>
								<CountUp
									from={scenario.resultNumber.from}
									to={scenario.resultNumber.to}
									startFrame={0}
									durationInFrames={20}
								/>
								{scenario.resultNumber.suffix}
								{'　'}
							</>
						) : null}
						{scenario.resultLine}
					</div>
				</FadeText>
			</Sequence>
		</AbsoluteFill>
	);
};
