import React from 'react';
import * as Icons from 'lucide-react';

interface DynamicIconProps {
  name: string;
  className?: string;
  size?: number;
}

export const DynamicIcon: React.FC<DynamicIconProps> = ({ name, className = 'w-5 h-5', size }) => {
  const iconDict = Icons as unknown as Record<string, React.ComponentType<{ className?: string; size?: number }>>;
  const IconComponent = iconDict[name] || Icons.LayoutGrid;
  return <IconComponent className={className} size={size} />;
};
