import React, { useState } from 'react';
import { 
  X, User, Settings as SettingsIcon, Shield, CreditCard, 
  Sparkles, Link, Code, Moon, Sun, Monitor, Type, 
  Volume2, Check, ChevronRight, Bell, Trash2, Globe
} from 'lucide-react';

const Settings = ({ isOpen, onClose, user }) => {
  const [activeTab, setActiveTab] = useState('general');

  if (!isOpen) return null;

  const tabs = [
    { id: 'general', label: 'General', icon: SettingsIcon },
    { id: 'account', label: 'Account', icon: User },
    { id: 'privacy', label: 'Privacy', icon: Shield },
    { id: 'billing', label: 'Billing', icon: CreditCard },
    { id: 'capabilities', label: 'Capabilities', icon: Sparkles },
    { id: 'connectors', label: 'Connectors', icon: Link },
    { id: 'code', label: 'MedAI Code', icon: Code },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case 'general':
        return (
          <div className="settings-tab-content">
            <section className="settings-section">
              <h3>Profile</h3>
              <div className="settings-group">
                <div className="settings-field">
                  <label>Full name</label>
                  <input type="text" defaultValue={user?.email?.split('@')[0]} placeholder="Enter your name" />
                </div>
                <div className="settings-field">
                  <label>What should MedAI call you?</label>
                  <input type="text" defaultValue={user?.email?.split('@')[0]} placeholder="Enter nickname" />
                </div>
              </div>
            </section>

            <section className="settings-section">
              <h3>Appearance</h3>
              <div className="settings-group">
                <label className="settings-label">Color mode</label>
                <div className="theme-selector">
                  <button className="theme-card active">
                    <div className="theme-preview dark"></div>
                    <span>Dark</span>
                  </button>
                  <button className="theme-card">
                    <div className="theme-preview light"></div>
                    <span>Light</span>
                  </button>
                  <button className="theme-card">
                    <div className="theme-preview auto"></div>
                    <span>Auto</span>
                  </button>
                </div>
              </div>
              
              <div className="settings-group">
                <label className="settings-label">Chat font</label>
                <div className="font-selector">
                  <button className="font-option active">Default</button>
                  <button className="font-option">Sans</button>
                  <button className="font-option">System</button>
                  <button className="font-option">Mono</button>
                </div>
              </div>
            </section>

            <section className="settings-section">
              <h3>Notifications</h3>
              <div className="settings-toggle-group">
                <div className="settings-toggle-item">
                  <div className="toggle-info">
                    <span className="toggle-title">Response completions</span>
                    <span className="toggle-desc">Get notified when MedAI has finished a long response.</span>
                  </div>
                  <div className="toggle-switch active"></div>
                </div>
              </div>
            </section>
          </div>
        );
      case 'account':
        return (
          <div className="settings-tab-content">
            <section className="settings-section">
              <h3>Account Information</h3>
              <div className="settings-info-card">
                <div className="info-row">
                  <span className="info-label">Email</span>
                  <span className="info-value">{user?.email}</span>
                </div>
                <div className="info-row">
                  <span className="info-label">User ID</span>
                  <span className="info-value-mono">{user?.id}</span>
                </div>
              </div>
            </section>
            
            <section className="settings-section">
              <h3>Danger Zone</h3>
              <button className="danger-btn">
                <Trash2 size={16} /> Delete Account
              </button>
            </section>
          </div>
        );
      default:
        return (
          <div className="settings-placeholder">
            <Sparkles size={48} className="placeholder-icon" />
            <h3>{tabs.find(t => t.id === activeTab)?.label} Settings</h3>
            <p>This section is being refined for your experience.</p>
          </div>
        );
    }
  };

  return (
    <div className="settings-view">
      <div className="settings-container">
        {/* Sidebar */}
        <aside className="settings-nav">
          <h2 className="settings-title">Settings</h2>
          <nav className="settings-nav-list">
            {tabs.map(tab => {
              const Icon = tab.icon;
              return (
                <button 
                  key={tab.id}
                  className={`settings-nav-item ${activeTab === tab.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon size={18} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="settings-main">
          <header className="settings-header">
            <button className="settings-close-btn" onClick={onClose} title="Close Settings">
              <X size={20} />
            </button>
          </header>
          <div className="settings-scroll-area">
            {renderContent()}
          </div>
        </main>
      </div>
    </div>
  );
};

export default Settings;
