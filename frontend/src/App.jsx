import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { queryHealthStream, getHealthStatus, getDomains } from './api';
import { supabase } from './supabase';
import Auth from './Auth';
import { MessageSquare, Plus, LogOut, PanelLeftClose, PanelLeft, Search, Settings as SettingsIcon, Globe, X, ChevronUp } from 'lucide-react';
import { getTranslations, getLLMLanguage, LANGUAGES } from './i18n';
import Settings from './components/Settings';
import { SidebarSkeleton, TopicSkeleton, MessageSkeleton } from './components/Skeleton';

export default function App() {
  const [user, setUser] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSessionsLoading, setIsSessionsLoading] = useState(true);
  const [isDomainsLoading, setIsDomainsLoading] = useState(true);
  const [isMessagesLoading, setIsMessagesLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [domains, setDomains] = useState([]);
  const [showChat, setShowChat] = useState(false);
  const [isRecovering, setIsRecovering] = useState(false);
  const [pastedChunks, setPastedChunks] = useState([]); // Claude-style paste cards
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [showLanguageMenu, setShowLanguageMenu] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState(localStorage.getItem('medai_lang') || 'en');
  
  const t = getTranslations(selectedLanguage);
  const quickQuestions = [t.q1, t.q2, t.q3, t.q4, t.q5, t.q6, t.q7, t.q8];
  
  // Cloud session state
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const profileMenuRef = useRef(null);

  // 1. Auth Listener
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      if (session?.user) fetchSessions(session.user.id);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY') {
        setIsRecovering(true);
      }
      setUser(session?.user ?? null);
      if (session?.user) fetchSessions(session.user.id);
    });

    return () => subscription.unsubscribe();
  }, []);

  // 2. Fetch basic info
  useEffect(() => {
    getHealthStatus().then(setStatus);
    setIsDomainsLoading(true);
    getDomains().then(data => {
      setDomains(data);
      setIsDomainsLoading(false);
    });
    const interval = setInterval(() => {
      getHealthStatus().then(setStatus);
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Close profile menu on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target)) {
        setShowProfileMenu(false);
        setShowLanguageMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);


  // == SUPABASE DB CALLS ==
  const fetchSessions = async (uid = user?.id) => {
    if (!uid) return;
    setIsSessionsLoading(true);
    const { data, error } = await supabase
      .from('chat_sessions')
      .select('*')
      .eq('user_id', uid)
      .order('updated_at', { ascending: false });
    if (!error && data) setSessions(data);
    setIsSessionsLoading(false);
  };

  const startNewChat = () => {
    setCurrentSessionId(null);
    setMessages([]);
    setShowChat(false);
    setShowSettings(false);
  };

  const loadSession = async (sessionId) => {
    if (isLoading) return;
    setCurrentSessionId(sessionId);
    setShowChat(true);
    setShowSettings(false);
    setMessages([]); // clear current UI temporarily
    setIsMessagesLoading(true);
    
    const { data, error } = await supabase
      .from('chat_messages')
      .select('*')
      .eq('session_id', sessionId)
      .order('created_at', { ascending: true });
      
    if (!error && data) {
      const formatted = data.map(msg => ({
        role: msg.role,
        content: msg.content,
        isError: msg.is_error,
        isStreaming: false
      }));
      setMessages(formatted);
    }
    setIsMessagesLoading(false);
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
  };

  // == CHAT LOGIC ==
  const handleSend = useCallback(async (text) => {
    // Combine any pasted chunks + inline input into the full query
    const pastedContent = pastedChunks.map(c => c.text).join('\n\n');
    const inlineText = (text || input).trim();
    const query = [pastedContent, inlineText].filter(Boolean).join('\n\n');
    if (!query || isLoading) return;

    // Add user message to UI immediately
    const userMsg = { role: 'user', content: query };
    const assistantMsg = { role: 'assistant', content: '', sources: [], isStreaming: true };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput('');
    setPastedChunks([]);
    resetTextareaHeight();
    setIsLoading(true);
    setShowChat(true);

    let activeSessionUUID = currentSessionId;
    
    // 1. Create a DB session if we don't have one
    if (!activeSessionUUID) {
      const { data, error } = await supabase.from('chat_sessions').insert({
        user_id: user.id,
        title: query.length > 40 ? query.substring(0, 40) + '...' : query
      }).select().single();
      
      if (!error && data) {
        activeSessionUUID = data.id;
        setCurrentSessionId(activeSessionUUID);
        fetchSessions(user.id);
      }
    }

    // 2. Save User Message to DB
    if (activeSessionUUID) {
      await supabase.from('chat_messages').insert({
        session_id: activeSessionUUID,
        user_id: user.id,
        role: 'user',
        content: query
      });
    }

    // 3. Stream from API
    let fullResponse = '';
    let isApiError = false;

    await queryHealthStream(query, activeSessionUUID || 'anon', {
      onToken: (token) => {
        fullResponse += token;
        setMessages((prev) => {
          const updated = [...prev];
          const last = { ...updated[updated.length - 1] };
          if (last.role === 'assistant') {
            last.content += token;
            updated[updated.length - 1] = last;
          }
          return updated;
        });
      },
      onDone: async () => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = { ...updated[updated.length - 1] };
          if (last.role === 'assistant') {
            last.isStreaming = false;
            updated[updated.length - 1] = last;
          }
          return updated;
        });
        setIsLoading(false);
        
        // 4. Save Assistant DB response
        if (activeSessionUUID) {
          await supabase.from('chat_messages').insert({
            session_id: activeSessionUUID,
            user_id: user.id,
            role: 'assistant',
            content: fullResponse
          });
          
          await supabase.from('chat_sessions')
            .update({ updated_at: new Date() })
            .eq('id', activeSessionUUID);
            
          fetchSessions(user.id);
        }
      },
      onError: async (err) => {
        const errorText = '⚠️ Failed to connect to the backend.';
        setMessages((prev) => {
          const updated = [...prev];
          const last = { ...updated[updated.length - 1] };
          if (last.role === 'assistant') {
            last.content = errorText;
            last.isStreaming = false;
            last.isError = true;
            updated[updated.length - 1] = last;
          }
          return updated;
        });
        setIsLoading(false);
        
        if (activeSessionUUID) {
          await supabase.from('chat_messages').insert({
            session_id: activeSessionUUID,
            user_id: user.id,
            role: 'assistant',
            content: errorText,
            is_error: true
          });
        }
      },
    }, getLLMLanguage(selectedLanguage), messages);
  }, [input, pastedChunks, isLoading, currentSessionId, user, selectedLanguage, messages]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Auto-resize textarea as user types
  const handleInputChange = (e) => {
    setInput(e.target.value);
    autoResize(e.target);
  };

  // Core resize logic — reusable for both typing and pasting
  const autoResize = (el) => {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 300) + 'px';
  };

  // On paste: if text is long (>300 chars), convert it to a card attachment
  const handlePaste = (e) => {
    const text = e.clipboardData?.getData('text') || '';
    if (text.length > 300) {
      e.preventDefault(); // don't dump into textarea
      setPastedChunks(prev => [
        ...prev,
        { id: Date.now(), text, preview: text.slice(0, 120) }
      ]);
    } else {
      // Short paste: let it go into textarea normally, then resize
      requestAnimationFrame(() => {
        if (inputRef.current) autoResize(inputRef.current);
      });
    }
  };

  // Reset textarea height after send
  const resetTextareaHeight = () => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
  };

  const handleTopicClick = (domain) => {
    const topicQueries = {
      'hair': 'What are the best treatments for hair loss?',
      'weight': 'How can I lose weight safely and sustainably?',
      'muscle': 'What is the best strategy to build muscle?',
      'hormones': 'How can I naturally optimize my testosterone levels?',
      'nutrition': 'What are the most important vitamins and supplements I should take?',
      'fitness': 'What is the best exercise routine for overall fitness?',
      'sleep': 'How can I improve my sleep quality?',
      'general': 'What are the most important things for overall health and longevity?',
    };
    handleSend(topicQueries[domain.id] || `Tell me about ${domain.name}`);
  };

  const hasMessages = messages.length > 0;

  // -- IF RECOVERING PASSWORD --
  if (isRecovering) return <Auth isRecovering={true} onRecovered={() => setIsRecovering(false)} />;

  // -- IF NOT AUTHENTICATED: Show Login Screen --
  if (!user) return <Auth />;

  // -- Filtered sessions for search --
  const filteredSessions = sessions.filter(s =>
    !searchQuery || s.title?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // -- IF AUTHENTICATED: Main Sidebar App --
  return (
    <div className="layout-container">
      {/* SIDEBAR */}
      <aside className={`sidebar ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
        {/* Top section: toggle + new chat */}
        <div className="sidebar-header">
          <button className="sidebar-toggle-btn" onClick={() => setSidebarOpen(prev => !prev)} title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}>
            {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
          </button>
          {sidebarOpen && (
            <button className="new-chat-btn" onClick={startNewChat}>
              <Plus size={18} /> {t.newChat}
            </button>
          )}
          {!sidebarOpen && (
            <button className="sidebar-icon-btn" onClick={startNewChat} title={t.newChat}>
              <Plus size={18} />
            </button>
          )}
        </div>

        {/* Search */}
        {sidebarOpen ? (
          <div className="sidebar-search">
            <Search size={14} className="sidebar-search-icon" />
            <input
              type="text"
              placeholder={t.searchChats}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="sidebar-search-input"
            />
            {searchQuery && (
              <button className="sidebar-search-clear" onClick={() => setSearchQuery('')}>
                <X size={12} />
              </button>
            )}
          </div>
        ) : (
          <button className="sidebar-icon-btn" onClick={() => setSidebarOpen(true)} title="Search" style={{ margin: '0 auto 4px' }}>
            <Search size={18} />
          </button>
        )}

        {/* Session list */}
        <div className="session-list">
          {sidebarOpen && <div className="session-label">{t.recentChats}</div>}
          
          {isSessionsLoading ? (
            sidebarOpen ? <SidebarSkeleton /> : null
          ) : (
            filteredSessions.map(session => (
              <div 
                key={session.id} 
                className={`session-item ${currentSessionId === session.id ? 'active' : ''}`}
                onClick={() => loadSession(session.id)}
                title={sidebarOpen ? '' : session.title}
              >
                <MessageSquare size={16} />
                {sidebarOpen && <span className="session-title">{session.title}</span>}
              </div>
            ))
          )}
          {sidebarOpen && filteredSessions.length === 0 && (
            <div style={{color: 'var(--text-muted)', fontSize: '0.85rem', padding: '10px 15px'}}>
              {searchQuery ? t.noMatchingChats : t.noChats}
            </div>
          )}
        </div>

        {/* Profile footer */}
        <div className="sidebar-footer" ref={profileMenuRef}>
          {/* Profile popup menu */}
          {showProfileMenu && sidebarOpen && (
            <div className="profile-popup">
              <div className="profile-popup-email">{user?.email}</div>
              <div className="profile-popup-divider" />
              <button className="profile-popup-item" onClick={() => { setShowProfileMenu(false); setShowSettings(true); }}>
                <SettingsIcon size={15} /> {t.settings}
              </button>
              <button className="profile-popup-item profile-popup-lang-trigger" onClick={() => setShowLanguageMenu(prev => !prev)}>
                <Globe size={15} /> {t.language}
                <ChevronUp size={14} className={`lang-chevron ${showLanguageMenu ? 'open' : ''}`} />
              </button>
              {showLanguageMenu && (
                <div className="language-submenu">
                  {LANGUAGES.map(lang => (
                    <button
                      key={lang.code}
                      className={`lang-option ${selectedLanguage === lang.code ? 'active' : ''}`}
                      onClick={() => { setSelectedLanguage(lang.code); setShowLanguageMenu(false); }}
                    >
                      {lang.label} {selectedLanguage === lang.code && '✓'}
                    </button>
                  ))}
                </div>
              )}
              <button className="profile-popup-item profile-popup-logout" onClick={handleLogout}>
                <LogOut size={15} /> {t.logOut}
              </button>
            </div>
          )}

          {/* Profile button */}
          <button className="profile-btn" onClick={() => { setShowProfileMenu(prev => !prev); setShowLanguageMenu(false); }}>
            <div className="profile-avatar">{user?.email?.[0]?.toUpperCase() || 'U'}</div>
            {sidebarOpen && (
              <>
                <div className="profile-info">
                  <span className="profile-name">{user?.email?.split('@')[0]}</span>
                  <span className="profile-plan">{t.freePlan}</span>
                </div>
                <ChevronUp size={14} className={`profile-chevron ${showProfileMenu ? 'open' : ''}`} />
              </>
            )}
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT AREA */}
      <main className="main-content-wrapper app">
        {showSettings ? (
          <Settings 
            isOpen={showSettings} 
            onClose={() => setShowSettings(false)} 
            user={user} 
          />
        ) : (
          <>
            {/* Top bar */}
            <header className="hero" style={{ padding: '24px 24px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', maxWidth: '850px', margin: '0 auto', width: '100%' }}>
              {!showChat && (
                <>
                  <div className="hero-icon">🧬</div>
                  <h1><span className="gradient-text">{t.heroTitle}</span></h1>
                  <p className="hero-subtitle">
                    {t.heroSubtitle}
                  </p>
                </>
              )}
            </header>

            {/* Home View */}
            {!hasMessages && !showChat && (
              <section className="topics-section">
                {isDomainsLoading ? (
                  <TopicSkeleton />
                ) : (
                  domains.length > 0 && (
                    <div className="topics-grid">
                      {domains.map((domain) => (
                        <button
                          key={domain.id}
                          className="topic-card"
                          onClick={() => handleTopicClick(domain)}
                        >
                          <span className="topic-icon">{domain.icon}</span>
                          <span className="topic-name">{domain.name}</span>
                        </button>
                      ))}
                    </div>
                  )
                )}
                <div style={{ textAlign: 'center', marginTop: '3rem' }}>
                  <button 
                    className="send-btn" 
                    style={{ margin: '0 auto', padding: '12px 32px', borderRadius: '24px', fontSize: '1rem', width: 'max-content' }} 
                    onClick={() => setShowChat(true)}
                  >
                    {t.startAsking}
                  </button>
                </div>
              </section>
            )}

            {/* Chat View */}
            {(hasMessages || showChat || isMessagesLoading) && (
            <section className="chat-section">
              {isMessagesLoading ? (
                <div className="chat-messages" style={{ padding: '24px' }}>
                  <MessageSkeleton />
                  <MessageSkeleton />
                  <MessageSkeleton />
                </div>
              ) : !hasMessages ? (
                <div className="welcome-screen">
                  <div className="welcome-icon">💬</div>
                  <h2 className="welcome-title">{t.welcomeTitle}</h2>
                  <p className="welcome-desc">
                    {t.welcomeDesc}
                  </p>
                  <div className="quick-questions">
                    {quickQuestions.map((q, i) => (
                      <button key={i} className="quick-question-btn" onClick={() => handleSend(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="chat-messages">
                  {messages.map((msg, idx) => {
                    if (msg.role === 'assistant' && msg.content === '' && isLoading) return null;
                    return (
                    <div key={idx} className={`message ${msg.role}`}>
                      <div className="message-avatar">
                        {msg.role === 'user' ? '👤' : '🧬'}
                      </div>
                      <div className="message-content">
                        <div className={`message-bubble ${msg.isError ? 'ood-message' : ''}`}>
                          {msg.role === 'assistant' ? (
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                table: ({ children }) => (
                                  <div className="table-scroll">
                                    <table>{children}</table>
                                  </div>
                                ),
                              }}
                            >
                              {msg.content}
                            </ReactMarkdown>
                          ) : (
                            msg.content
                          )}
                        </div>
                      </div>
                    </div>
                  )})}
                  
                  {isLoading && messages[messages.length - 1]?.content === '' && (
                    <div className="typing-indicator">
                      <div className="message-avatar" style={{background: 'linear-gradient(135deg, #00d4aa, #0ea5e9)'}}>
                        🧬
                      </div>
                      <div className="typing-dots">
                        <span></span><span></span><span></span>
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}

              {/* Input Area */}
              <div className="chat-input-area">
                {/* Paste attachment cards */}
                {pastedChunks.length > 0 && (
                  <div className="paste-cards-grid">
                    {pastedChunks.map(chunk => (
                      <div key={chunk.id} className="paste-card">
                        <div className="paste-card-preview">{chunk.preview}…</div>
                        <div className="paste-card-footer">
                          <span className="paste-label">{t.pasted}</span>
                          <button
                            className="paste-card-remove"
                            onClick={() => setPastedChunks(prev => prev.filter(c => c.id !== chunk.id))}
                            title="Remove"
                          >✕</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="chat-input-wrapper">
                  <textarea
                    ref={inputRef}
                    className="chat-input"
                    value={input}
                    onChange={handleInputChange}
                    onPaste={handlePaste}
                    onKeyDown={handleKeyDown}
                    placeholder={pastedChunks.length > 0 ? t.inputPlaceholderPasted : t.inputPlaceholder}
                    rows={1}
                    disabled={isLoading}
                    style={{ overflowY: 'auto', resize: 'none' }}
                  />
                  <button
                    className="send-btn"
                    onClick={() => handleSend()}
                    disabled={isLoading || (!input.trim() && pastedChunks.length === 0)}
                  >
                    ➤
                  </button>
                </div>
              </div>
            </section>
            )}

            <footer className="status-bar" style={{ marginTop: 'auto' }}>
              <div className="status-item">
                <span className={`status-dot ${status ? 'online' : 'offline'}`}></span>
                {status ? t.connected : t.backendOffline}
              </div>
              {status && (
                <>
                  <div className="status-item">🤖 {status.model}</div>
                  <div className="status-item">🔍 {t.dbSynced}</div>
                </>
              )}
            </footer>
          </>
        )}
      </main>
    </div>
  );
}
