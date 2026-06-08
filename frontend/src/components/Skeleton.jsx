import React from 'react';

const Skeleton = ({ className, width, height, borderRadius = 'var(--radius-md)', style }) => {
  return (
    <div 
      className={`skeleton-loader ${className || ''}`}
      style={{
        width: width || '100%',
        height: height || '20px',
        borderRadius,
        ...style
      }}
    />
  );
};

export const SidebarSkeleton = () => (
  <div className="sidebar-skeleton">
    {[1, 2, 3, 4, 5].map(i => (
      <div key={i} className="sidebar-skeleton-item">
        <Skeleton width="20px" height="20px" borderRadius="4px" />
        <Skeleton width={`${Math.floor(Math.random() * (80 - 40 + 1) + 40)}%`} height="14px" />
      </div>
    ))}
  </div>
);

export const TopicSkeleton = () => (
  <div className="topic-skeleton-grid">
    {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
      <div key={i} className="topic-skeleton-card">
        <Skeleton width="40px" height="40px" borderRadius="12px" style={{ marginBottom: '12px' }} />
        <Skeleton width="60%" height="16px" style={{ marginBottom: '8px' }} />
        <Skeleton width="80%" height="12px" />
      </div>
    ))}
  </div>
);

export const MessageSkeleton = () => (
  <div className="message-skeleton">
    <div className="message-skeleton-header">
      <Skeleton width="32px" height="32px" borderRadius="50%" />
      <Skeleton width="100px" height="14px" />
    </div>
    <div className="message-skeleton-body">
      <Skeleton width="90%" height="16px" style={{ marginBottom: '8px' }} />
      <Skeleton width="95%" height="16px" style={{ marginBottom: '8px' }} />
      <Skeleton width="70%" height="16px" />
    </div>
  </div>
);

export default Skeleton;
