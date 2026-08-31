import React from 'react';

/**
 * Placeholder "digital tool" screen used until real product screenshots are
 * dropped into public/screenshots and referenced from scenarios.ts.
 */
export const MockScreen: React.FC<{title: string; rows: {label: string; value: string}[]}> = ({
	title,
	rows,
}) => {
	return (
		<div
			style={{
				width: '100%',
				height: '100%',
				background: 'linear-gradient(180deg, #f4f6fb 0%, #ffffff 40%)',
				padding: 24,
				fontFamily: 'sans-serif',
				boxSizing: 'border-box',
			}}
		>
			<div style={{fontSize: 22, fontWeight: 700, color: '#1a1a2e', marginBottom: 18}}>
				{title}
			</div>
			{rows.map((row) => (
				<div
					key={row.label}
					style={{
						background: 'white',
						borderRadius: 12,
						padding: '14px 18px',
						marginBottom: 12,
						boxShadow: '0 4px 14px rgba(20,20,50,0.06)',
						display: 'flex',
						justifyContent: 'space-between',
						alignItems: 'center',
					}}
				>
					<span style={{color: '#555', fontSize: 16}}>{row.label}</span>
					<span style={{color: '#1a1a2e', fontSize: 20, fontWeight: 700}}>{row.value}</span>
				</div>
			))}
		</div>
	);
};
