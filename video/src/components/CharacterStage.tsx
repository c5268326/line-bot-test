import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Character, Mood} from './Character';

type CharacterStageProps = {
	armRaise: number;
	mood: Mood;
	entrance?: boolean;
	talking?: boolean;
	accentColor?: string;
	background?: string;
	caption?: string;
	scale?: number;
	children?: React.ReactNode;
};

export const CharacterStage: React.FC<CharacterStageProps> = ({
	armRaise,
	mood,
	entrance,
	talking,
	accentColor,
	background = '#12172c',
	caption,
	scale = 1,
	children,
}) => {
	return (
		<AbsoluteFill style={{background}}>
			<AbsoluteFill
				style={{
					alignItems: 'center',
					justifyContent: 'center',
					transform: `scale(${scale})`,
				}}
			>
				<svg viewBox="0 0 400 560" width={560} height={784}>
					<Character
						armRaise={armRaise}
						mood={mood}
						entrance={entrance}
						talking={talking}
						accentColor={accentColor}
					/>
				</svg>
			</AbsoluteFill>

			{caption && (
				<div
					style={{
						position: 'absolute',
						left: 0,
						right: 0,
						bottom: 140,
						padding: '0 70px',
					}}
				>
					<div
						style={{
							background: 'rgba(0,0,0,0.55)',
							borderRadius: 16,
							padding: '22px 28px',
							textAlign: 'center',
						}}
					>
						<span style={{color: 'white', fontSize: 34, fontWeight: 700, lineHeight: 1.5}}>
							{caption}
						</span>
					</div>
				</div>
			)}

			{children && (
				<div
					style={{
						position: 'absolute',
						left: 0,
						right: 0,
						bottom: 260,
						display: 'flex',
						justifyContent: 'center',
					}}
				>
					{children}
				</div>
			)}
		</AbsoluteFill>
	);
};
