import { useState, useMemo } from 'react';
import { supabase } from './supabase';
import { Eye, EyeOff, Check, X as XIcon } from 'lucide-react';

// Password validation rules
const PASSWORD_RULES = [
  { id: 'length',    label: 'At least 8 characters',          test: (p) => p.length >= 8 },
  { id: 'uppercase', label: 'One uppercase letter (A-Z)',     test: (p) => /[A-Z]/.test(p) },
  { id: 'lowercase', label: 'One lowercase letter (a-z)',     test: (p) => /[a-z]/.test(p) },
  { id: 'number',    label: 'One number (0-9)',               test: (p) => /[0-9]/.test(p) },
  { id: 'special',   label: 'One special character (!@#$...)', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

function PasswordStrength({ password }) {
  const results = PASSWORD_RULES.map(rule => ({ ...rule, passed: rule.test(password) }));
  const passedCount = results.filter(r => r.passed).length;
  const strengthPercent = (passedCount / PASSWORD_RULES.length) * 100;

  const strengthColor =
    strengthPercent <= 20 ? '#ef4444' :
    strengthPercent <= 40 ? '#f97316' :
    strengthPercent <= 60 ? '#f59e0b' :
    strengthPercent <= 80 ? '#84cc16' : '#00d4aa';

  const strengthLabel =
    strengthPercent <= 20 ? 'Very Weak' :
    strengthPercent <= 40 ? 'Weak' :
    strengthPercent <= 60 ? 'Fair' :
    strengthPercent <= 80 ? 'Good' : 'Strong';

  if (!password) return null;

  return (
    <div className="password-strength-container">
      {/* Strength bar */}
      <div className="password-strength-bar-track">
        <div
          className="password-strength-bar-fill"
          style={{ width: `${strengthPercent}%`, background: strengthColor }}
        />
      </div>
      <div className="password-strength-label" style={{ color: strengthColor }}>
        {strengthLabel}
      </div>

      {/* Checklist */}
      <ul className="password-rules-list">
        {results.map(rule => (
          <li key={rule.id} className={`password-rule ${rule.passed ? 'passed' : ''}`}>
            {rule.passed
              ? <Check size={14} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
              : <XIcon size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
            }
            <span>{rule.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Auth({ isRecovering = false, onRecovered }) {
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [retypePassword, setRetypePassword] = useState('');
  
  const [isLogin, setIsLogin] = useState(true);
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Whether to show the strength indicator (signup or recovery only)
  const showStrengthIndicator = (!isLogin && !isForgotPassword) || isRecovering;

  // Check if all password rules pass
  const allRulesPass = useMemo(
    () => PASSWORD_RULES.every(rule => rule.test(password)),
    [password]
  );

  const handleAuth = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    setSuccessMsg('');

    try {
      if (isRecovering) {
        if (!allRulesPass) {
          throw new Error('Please meet all password requirements');
        }
        if (password !== retypePassword) {
          throw new Error('Passwords do not match');
        }
        const { error } = await supabase.auth.updateUser({ password });
        if (error) throw error;
        setSuccessMsg('Password updated successfully!');
        if (onRecovered) setTimeout(() => onRecovered(), 1500);
      } else if (isForgotPassword) {
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: window.location.origin,
        });
        if (error) throw error;
        setSuccessMsg('Password reset email sent! Check your inbox.');
      } else if (isLogin) {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        if (!allRulesPass) {
          throw new Error('Please meet all password requirements');
        }
        if (password !== retypePassword) {
          throw new Error('Passwords do not match');
        }
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setSuccessMsg('Success! Check your email or try logging in.');
      }
    } catch (error) {
      setErrorMsg(error.error_description || error.message);
    } finally {
      setLoading(false);
    }
  };

  // Determine Title & Subtitle based on state
  let title = "MedAI";
  let subtitle = "Sign in to access your chats";
  let buttonText = "Sign In";
  
  if (isRecovering) {
    title = "Reset Password";
    subtitle = "Create a new strong password";
    buttonText = "Update Password";
  } else if (isForgotPassword) {
    title = "Forgot Password";
    subtitle = "Enter your email to receive a reset link";
    buttonText = "Send Reset Link";
  } else if (!isLogin) {
    title = "MedAI";
    subtitle = "Create an account to save chats";
    buttonText = "Sign Up";
  }

  return (
    <div className="auth-container">
      <div className="glass-panel auth-panel">
        <div style={{ textAlign: 'center', marginBottom: '30px' }}>
          <div className="hero-icon" style={{ fontSize: '48px', marginBottom: '10px' }}>🧬</div>
          <h2><span className="gradient-text">{title}</span></h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>{subtitle}</p>
        </div>
        
        <form onSubmit={handleAuth} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
          
          {/* Email: Hide if recovering password */}
          {!isRecovering && (
            <input 
              className="chat-input"
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{ minHeight: '45px' }}
            />
          )}

          {/* Passwords: Hide if just asking for a reset link */}
          {!isForgotPassword && (
            <div style={{ position: 'relative' }}>
              <input 
                className="chat-input"
                type={showPassword ? "text" : "password"}
                placeholder={isRecovering ? "New password" : "Password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                style={{ minHeight: '45px', width: '100%', paddingRight: '40px' }}
              />
              <button 
                type="button" 
                onClick={(e) => { e.preventDefault(); setShowPassword(!showPassword); }}
                style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex' }}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          )}

          {/* Password Strength Indicator */}
          {showStrengthIndicator && <PasswordStrength password={password} />}

          {/* Retype Password: Show if Signing up OR Recovering */}
          {(!isLogin && !isForgotPassword) || isRecovering ? (
            <div style={{ position: 'relative' }}>
              <input 
                className="chat-input"
                type={showPassword ? "text" : "password"}
                placeholder="Retype password"
                value={retypePassword}
                onChange={(e) => setRetypePassword(e.target.value)}
                required
                style={{ minHeight: '45px', width: '100%', paddingRight: '40px' }}
              />
              <button 
                type="button" 
                onClick={(e) => { e.preventDefault(); setShowPassword(!showPassword); }}
                style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex' }}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          ) : null}
          
          {errorMsg && <div style={{ color: 'var(--accent-danger)', fontSize: '0.85rem', textAlign: 'center' }}>{errorMsg}</div>}
          {successMsg && <div style={{ color: 'var(--accent-primary)', fontSize: '0.85rem', textAlign: 'center' }}>{successMsg}</div>}
          
          <button className="send-btn" disabled={loading} style={{ width: '100%', height: '45px', borderRadius: '8px', fontSize: '1rem', marginTop: '10px' }}>
            {loading ? 'Processing...' : buttonText}
          </button>
        </form>

        {/* Dynamic Footer Links */}
        {!isRecovering && (
          <div style={{ textAlign: 'center', marginTop: '24px', fontSize: '0.9rem' }}>
            {isForgotPassword ? (
              <span 
                style={{ color: 'var(--text-secondary)', cursor: 'pointer' }}
                onClick={() => { setIsForgotPassword(false); setErrorMsg(''); setSuccessMsg(''); }}
              >
                Back to <span style={{ color: 'var(--accent-primary)', fontWeight: '600' }}>Login</span>
              </span>
            ) : (
              <>
                <div style={{ marginBottom: '10px' }}>
                  <span 
                    style={{ color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem', textDecoration: 'underline' }}
                    onClick={() => { setIsForgotPassword(true); setErrorMsg(''); setSuccessMsg(''); }}
                  >
                    Forgot your password?
                  </span>
                </div>
                <div style={{ color: 'var(--text-secondary)' }}>
                  {isLogin ? "Don't have an account? " : "Already have an account? "}
                  <span 
                    style={{ color: 'var(--accent-primary)', cursor: 'pointer', fontWeight: '600' }}
                    onClick={() => {
                      setIsLogin(!isLogin);
                      setErrorMsg('');
                      setSuccessMsg('');
                      setRetypePassword('');
                      setPassword('');
                    }}
                  >
                    {isLogin ? 'Sign Up' : 'Sign In'}
                  </span>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
