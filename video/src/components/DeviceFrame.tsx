import React from 'react';

type DeviceFrameProps = {
	variant: 'phone' | 'browser';
	children: React.ReactNode;
};

export const DeviceFrame: React.FC<DeviceFrameProps> = ({variant, children}) => {
	if (variant === 'phone') {
		return (
			<div
				style={{
					width: '100%',
					height: '100%',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
				}}
			>
				<div
					style={{
						width: 420,
						height: '90%',
						borderRadius: 48,
						background: '#111',
						padding: 14,
						boxShadow: '0 40px 80px rgba(0,0,0,0.45)',
						position: 'relative',
					}}
				>
					<div
						style={{
							position: 'absolute',
							top: 14,
							left: '50%',
							transform: 'translateX(-50%)',
							width: 120,
							height: 24,
							borderRadius: 12,
							background: '#111',
							zIndex: 2,
						}}
					/>
					<div
						style={{
							width: '100%',
							height: '100%',
							borderRadius: 34,
							overflow: 'hidden',
							background: '#fff',
							position: 'relative',
						}}
					>
						{children}
					</div>
				</div>
			</div>
		);
	}

	return (
		<div
			style={{
				width: '100%',
				height: '100%',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
			}}
		>
			<div
				style={{
					width: '86%',
					height: '80%',
					borderRadius: 16,
					background: '#e6e8eb',
					boxShadow: '0 40px 80px rgba(0,0,0,0.35)',
					overflow: 'hidden',
					display: 'flex',
					flexDirection: 'column',
				}}
			>
				<div
					style={{
						height: 36,
						background: '#d8dadd',
						display: 'flex',
						alignItems: 'center',
						gap: 8,
						paddingLeft: 16,
						flexShrink: 0,
					}}
				>
					{['#ff5f57', '#febc2e', '#28c840'].map((color) => (
						<div
							key={color}
							style={{
								width: 12,
								height: 12,
								borderRadius: '50%',
								background: color,
							}}
						/>
					))}
				</div>
				<div style={{flex: 1, position: 'relative', background: '#fff'}}>
					{children}
				</div>
			</div>
		</div>
	);
};
