'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { supabase } from '@/lib/supabase';
import {
  MapPin,
  Calendar,
  Clock,
  DollarSign,
  Navigation,
  Share2,
  ExternalLink,
  Filter,
  CheckCircle2,
  AlertCircle,
  LocateFixed,
  Search,
  ChevronDown,
  ChevronUp,
  Check,
} from 'lucide-react';

interface Rink {
  id: string;
  name: string;
  address: string;
  city: string;
  zip_code: string;
  latitude: number;
  longitude: number;
  website_url: string;
}

interface HockeySession {
  id: string;
  session_type: string;
  title: string;
  session_date: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  cost: number | null;
  cost_notes: string | null;
  age_restriction: string | null;
  registration_required: boolean;
  availability_status: string;
  booking_url: string | null;
  source_url: string;
  is_verified: boolean;
  rinks: Rink;
}

const SESSION_CATEGORIES = ['All', 'Stick & Puck', 'Stick Time', 'Open Hockey', 'Shinny'];
const DATE_FILTERS = [
  { id: 'all', label: 'All (14 Days)' },
  { id: 'today', label: 'Today' },
  { id: 'tomorrow', label: 'Tomorrow' },
  { id: '3days', label: 'Next 3 Days' },
];
const DEFAULT_VISIBLE_SESSIONS = 3;
const LOCATION_STORAGE_KEY = 'pucked_user_location_v1';

function getLocalDateOffset(daysOffset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysOffset);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function calculateDistanceMiles(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 3958.8;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c * 10) / 10;
}

function formatTime12Hour(timeStr: string): string {
  if (!timeStr) return '';
  const [hoursStr, minutesStr] = timeStr.split(':');
  let hours = parseInt(hoursStr, 10);
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${hours}:${minutesStr} ${ampm}`;
}

function formatDateNice(dateStr: string): string {
  if (!dateStr) return '';
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function getBadgeStyle(sessionType: string): string {
  switch (sessionType) {
    case 'Stick & Puck':
      return 'bg-[#CE1126]/20 text-[#FF8992]';
    case 'Stick Time':
      return 'bg-[#4B9CD3]/20 text-[#96D0FA]';
    case 'Open Hockey':
      return 'bg-emerald-400/15 text-emerald-300';
    default:
      return 'bg-white/10 text-zinc-200';
  }
}

export default function Home() {
  const [sessions, setSessions] = useState<HockeySession[]>([]);
  const [allRinks, setAllRinks] = useState<Rink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string>('All');
  const [selectedDateRange, setSelectedDateRange] = useState<string>('all');
  const [expandedRinks, setExpandedRinks] = useState<Record<string, boolean>>({});
  const [dateBounds, setDateBounds] = useState<{ today: string; tomorrow: string; threeDays: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [maxRadius, setMaxRadius] = useState<number>(100);
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [locationStatus, setLocationStatus] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [logoError, setLogoError] = useState<boolean>(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(LOCATION_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (typeof parsed?.lat === 'number' && typeof parsed?.lng === 'number') {
          setUserLocation(parsed);
          setLocationStatus('Sorted by nearest active rink');
        }
      }
    } catch {
      // Ignore storage errors
    }

    if (typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          setUserLocation(coords);
          setLocationStatus('Sorted by nearest active rink');
          try {
            window.localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(coords));
          } catch {
            // Ignore storage errors
          }
        },
        () => {
          // Silent fallback on initial mount
        },
        { timeout: 8000, maximumAge: 300000 }
      );
    }
  }, []);

  useEffect(() => {
    async function fetchSessions() {
      setLoading(true);
      const today = getLocalDateOffset(0);
      setDateBounds({
        today,
        tomorrow: getLocalDateOffset(1),
        threeDays: getLocalDateOffset(2),
      });
      const [rinksRes, sessionsRes] = await Promise.all([
        supabase
          .from('rinks')
          .select('id, name, address, city, zip_code, latitude, longitude, website_url')
          .order('name', { ascending: true }),
        supabase
          .from('sessions')
          .select(`
            *,
            rinks (
              id,
              name,
              address,
              city,
              zip_code,
              latitude,
              longitude,
              website_url
            )
          `)
          .gte('session_date', today)
          .order('session_date', { ascending: true })
          .order('start_time', { ascending: true })
          .limit(150),
      ]);

      if (sessionsRes.error || rinksRes.error) {
        setError('Could not load sessions. Check your Supabase connection.');
      } else {
        setAllRinks((rinksRes.data as unknown as Rink[]) || []);
        setSessions((sessionsRes.data as unknown as HockeySession[]) || []);
      }
      setLoading(false);
    }
    fetchSessions();
  }, []);

  const toggleRinkExpanded = (rinkId: string) => {
    setExpandedRinks((prev) => ({ ...prev, [rinkId]: !prev[rinkId] }));
  };

  const handleUseGPS = () => {
    if (!navigator.geolocation) {
      setLocationStatus('GPS not supported on this browser.');
      return;
    }
    setLocationStatus('Locating...');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setUserLocation(coords);
        setLocationStatus('Sorted by nearest active rink');
        try {
          window.localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(coords));
        } catch {
          // Ignore storage errors
        }
      },
      () => {
        setLocationStatus('Location permission denied — search by town or ZIP below');
      }
    );
  };

  const handleShare = async (session: HockeySession) => {
    const shareText = `🏒 ${session.session_type} at ${session.rinks?.name} (${session.rinks?.city}, NJ)\n📅 ${formatDateNice(session.session_date)} • ${formatTime12Hour(session.start_time)} - ${formatTime12Hour(session.end_time)}\n🔗 ${session.booking_url || session.source_url}`;
    await navigator.clipboard.writeText(shareText);
    setCopiedId(session.id);
    setTimeout(() => setCopiedId(null), 2500);
  };

  const groupedRinks = useMemo(() => {
    const todayStr = dateBounds?.today ?? '';
    const tomorrowStr = dateBounds?.tomorrow ?? '';
    const threeDaysStr = dateBounds?.threeDays ?? '';

    const filtered = sessions
      .map((session) => {
        const distance =
          userLocation && session.rinks
            ? calculateDistanceMiles(
                userLocation.lat,
                userLocation.lng,
                session.rinks.latitude,
                session.rinks.longitude
              )
            : null;
        return { ...session, distance };
      })
      .filter((s) => {
        if (selectedType !== 'All' && s.session_type !== selectedType) return false;
        if (dateBounds) {
          if (selectedDateRange === 'today' && s.session_date !== todayStr) return false;
          if (selectedDateRange === 'tomorrow' && s.session_date !== tomorrowStr) return false;
          if (selectedDateRange === '3days' && (s.session_date < todayStr || s.session_date > threeDaysStr)) return false;
        }
        if (s.distance !== null && s.distance > maxRadius) return false;
        if (searchQuery.trim() !== '') {
          const q = searchQuery.toLowerCase();
          const matchRink = s.rinks?.name.toLowerCase().includes(q);
          const matchCity = s.rinks?.city.toLowerCase().includes(q);
          const matchZip = s.rinks?.zip_code.includes(q);
          const matchTitle = s.title?.toLowerCase().includes(q);
          if (!matchRink && !matchCity && !matchZip && !matchTitle) return false;
        }
        return true;
      });

    const rinkMap = new Map<string, { rink: Rink; distance: number | null; sessions: HockeySession[] }>();

    allRinks.forEach((rink) => {
      const distance = userLocation
        ? calculateDistanceMiles(userLocation.lat, userLocation.lng, rink.latitude, rink.longitude)
        : null;
      if (distance !== null && distance > maxRadius) return;
      if (searchQuery.trim() !== '') {
        const q = searchQuery.toLowerCase();
        const matchRink = rink.name.toLowerCase().includes(q);
        const matchCity = rink.city.toLowerCase().includes(q);
        const matchZip = rink.zip_code.includes(q);
        const hasMatchingSession = filtered.some((s) => s.rinks?.id === rink.id);
        if (!matchRink && !matchCity && !matchZip && !hasMatchingSession) return;
      }
      rinkMap.set(rink.id, {
        rink,
        distance,
        sessions: [],
      });
    });

    filtered.forEach((session) => {
      if (!session.rinks) return;
      const rinkId = session.rinks.id;
      if (!rinkMap.has(rinkId)) {
        rinkMap.set(rinkId, {
          rink: session.rinks,
          distance: session.distance,
          sessions: [],
        });
      }
      rinkMap.get(rinkId)!.sessions.push(session);
    });

    return Array.from(rinkMap.values()).sort((a, b) => {
      const aHasEvents = a.sessions.length > 0;
      const bHasEvents = b.sessions.length > 0;
      if (aHasEvents !== bHasEvents) {
        return aHasEvents ? -1 : 1;
      }
      if (a.distance !== null && b.distance !== null) {
        return a.distance - b.distance;
      }
      return a.rink.name.localeCompare(b.rink.name);
    });
  }, [allRinks, sessions, selectedType, selectedDateRange, dateBounds, searchQuery, maxRadius, userLocation]);

  return (
    /* Pixel Neutral Dark Graphite Canvas (#121315) */
    <div className="min-h-screen bg-[#121315] text-[#E3E2E6] pb-24 selection:bg-[#CE1126]/30 selection:text-white">
      {/* Pixel Top App Bar */}
      <header className="sticky top-0 z-20 bg-[#121315]/90 backdrop-blur-xl px-4 pt-4 pb-3">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-3">
          <div className="flex items-center gap-3.5">
            {!logoError ? (
              <img
                src="/logo.png"
                alt="Pucked Logo"
                onError={() => setLogoError(true)}
                className="w-12 h-12 rounded-[18px] object-contain bg-[#1C1D20] p-1.5 shrink-0 shadow-md"
              />
            ) : (
              <div className="w-12 h-12 rounded-[18px] bg-[#CE1126] text-white font-black text-2xl flex items-center justify-center shrink-0 shadow-md">
                P
              </div>
            )}
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-[24px] font-extrabold tracking-tight text-white leading-none">
                  Pucked
                </h1>
                <span className="text-[10px] font-bold uppercase tracking-wider bg-[#26272B] text-[#C4C6D0] px-2.5 py-0.5 rounded-full">
                  NJ Live
                </span>
              </div>
              <p className="text-xs font-medium text-[#90909A] mt-1">
                New Jersey ice-time finder
              </p>
            </div>
          </div>

          {/* Material 3 Stadium Pill Button */}
          <button
            onClick={handleUseGPS}
            className={`inline-flex items-center gap-2 text-xs font-bold px-5 py-3 rounded-full transition-all duration-200 active:scale-[0.96] cursor-pointer shadow-sm ${
              userLocation
                ? 'bg-[#26272B] text-[#96D0FA] hover:bg-[#303136]'
                : 'bg-[#CE1126] hover:bg-[#E01930] text-white'
            }`}
          >
            <LocateFixed className="w-4 h-4" />
            {userLocation ? 'GPS Sorted' : 'Near Me'}
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 pt-2 space-y-5">
        {/* Material 3 Surface Container (#1B1C1F, 32px Pixel Squircle) */}
        <div className="bg-[#1B1C1F] rounded-[32px] p-4 sm:p-5 space-y-4 shadow-lg shadow-black/30">
          {/* Pixel Launcher-style Search Pill */}
          <div className="flex flex-col sm:flex-row gap-2.5">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-[#90909A] absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search rink, town, ZIP, or Stick & Puck..."
                className="w-full h-12 bg-[#26272B] hover:bg-[#2E2F34] focus:bg-[#323339] rounded-full pl-11 pr-5 text-sm font-medium text-white placeholder-[#90909A] transition-colors focus:outline-none focus:ring-2 focus:ring-[#96D0FA]"
              />
            </div>
            {userLocation && (
              <select
                value={maxRadius}
                onChange={(e) => setMaxRadius(Number(e.target.value))}
                className="h-12 bg-[#26272B] hover:bg-[#2E2F34] rounded-full px-5 text-sm font-semibold text-[#E3E2E6] transition-colors focus:outline-none focus:ring-2 focus:ring-[#96D0FA] cursor-pointer"
              >
                <option value={10}>Within 10 mi</option>
                <option value={25}>Within 25 mi</option>
                <option value={50}>Within 50 mi</option>
                <option value={100}>Within 100 mi</option>
              </select>
            )}
          </div>

          {locationStatus && (
            <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#96D0FA] bg-[#4B9CD3]/15 px-3.5 py-1.5 rounded-full">
              <MapPin className="w-3.5 h-3.5" />
              <span>{locationStatus}</span>
            </div>
          )}

          {/* Material 3 Date Range Filter Chips */}
          <div className="flex items-center gap-2 overflow-x-auto pb-0.5">
            <Calendar className="w-4 h-4 text-[#90909A] shrink-0 mr-0.5" />
            {DATE_FILTERS.map((df) => {
              const active = selectedDateRange === df.id;
              return (
                <button
                  key={df.id}
                  onClick={() => setSelectedDateRange(df.id)}
                  className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold whitespace-nowrap transition-all duration-150 active:scale-[0.96] cursor-pointer ${
                    active
                      ? 'bg-[#E3E2E6] text-[#121315] shadow-sm'
                      : 'bg-[#26272B] text-[#C4C6D0] hover:bg-[#303136] hover:text-white'
                  }`}
                >
                  {active && <Check className="w-3.5 h-3.5 stroke-[2.75]" />}
                  {df.label}
                </button>
              );
            })}
          </div>

          {/* Material 3 Session Type Filter Chips */}
          <div className="flex items-center gap-2 overflow-x-auto pb-0.5">
            <Filter className="w-4 h-4 text-[#90909A] shrink-0 mr-0.5" />
            {SESSION_CATEGORIES.map((type) => {
              const active = selectedType === type;
              return (
                <button
                  key={type}
                  onClick={() => setSelectedType(type)}
                  className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold whitespace-nowrap transition-all duration-150 active:scale-[0.96] cursor-pointer ${
                    active
                      ? 'bg-[#CE1126] text-white shadow-sm'
                      : 'bg-[#26272B] text-[#C4C6D0] hover:bg-[#303136] hover:text-white'
                  }`}
                >
                  {active && <Check className="w-3.5 h-3.5 stroke-[2.75]" />}
                  {type}
                </button>
              );
            })}
          </div>
        </div>

        {loading && (
          <div className="bg-[#1B1C1F] rounded-[32px] text-center py-14 text-[#C4C6D0] text-sm font-semibold">
            Loading upcoming New Jersey ice times...
          </div>
        )}

        {error && (
          <div className="bg-[#3B181C] text-[#FFB4AB] rounded-[28px] p-5 text-sm flex items-start gap-3">
            <AlertCircle className="w-5 h-5 shrink-0 text-[#FF8992] mt-0.5" />
            <div>{error}</div>
          </div>
        )}

        {!loading && !error && groupedRinks.length === 0 && (
          <div className="text-center py-12 bg-[#1B1C1F] rounded-[32px] p-6 space-y-1.5">
            <p className="text-white font-bold">No sessions match your filters.</p>
            <p className="text-xs text-[#90909A]">
              Try switching back to &ldquo;All (14 Days)&rdquo; or clearing your search box.
            </p>
          </div>
        )}

        {/* Rink Cards: Neutral Dark Graphite Surface Containers (#1B1C1F, rounded-[32px]) */}
        <div className="space-y-4">
          {groupedRinks.map(({ rink, distance, sessions: rinkSessions }) => {
            const isExpanded = !!expandedRinks[rink.id];
            const visibleSessions = isExpanded
              ? rinkSessions
              : rinkSessions.slice(0, DEFAULT_VISIBLE_SESSIONS);
            const hiddenCount = rinkSessions.length - DEFAULT_VISIBLE_SESSIONS;

            const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(
              `${rink.name}, ${rink.address}, ${rink.city}, NJ ${rink.zip_code}`
            )}`;

            return (
              <div
                key={rink.id}
                className="bg-[#1B1C1F] rounded-[32px] p-5 sm:p-6 shadow-lg shadow-black/25 space-y-4"
              >
                {/* Rink Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1">
                    <a
                      href={rink.website_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[20px] font-extrabold text-white hover:text-[#96D0FA] transition-colors leading-snug inline-flex items-center gap-1.5"
                    >
                      {rink.name}
                      <ExternalLink className="w-4 h-4 text-[#96D0FA] shrink-0" />
                    </a>
                    <p className="text-xs font-medium text-[#90909A] flex items-center gap-1.5">
                      <MapPin className="w-3.5 h-3.5 shrink-0 text-[#90909A]" />
                      <span>
                        {rink.address}, {rink.city}, NJ {rink.zip_code}
                      </span>
                    </p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {distance !== null && (
                      <span className="text-xs font-bold text-[#96D0FA] bg-[#26272B] px-3.5 py-2 rounded-full">
                        {distance} mi
                      </span>
                    )}
                    <a
                      href={mapsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 bg-[#96D0FA] hover:bg-[#B2DEFC] text-[#07263A] text-xs font-extrabold px-4 py-2.5 rounded-full transition-all duration-150 active:scale-[0.96] shadow-sm"
                    >
                      <Navigation className="w-3.5 h-3.5" />
                      Directions
                    </a>
                  </div>
                </div>

                {/* Sessions Inside Rink */}
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between px-1">
                    <p className="text-[11px] font-extrabold text-[#90909A] uppercase tracking-widest">
                      {rinkSessions.length === 0
                        ? 'Upcoming Sessions (0)'
                        : isExpanded || rinkSessions.length <= DEFAULT_VISIBLE_SESSIONS
                        ? `Upcoming Sessions (${rinkSessions.length})`
                        : `Next ${DEFAULT_VISIBLE_SESSIONS} of ${rinkSessions.length} Sessions`}
                    </p>
                  </div>

                  {rinkSessions.length === 0 && (
                    <div className="bg-[#26272B] rounded-[24px] p-4 flex items-center justify-between gap-3 flex-wrap">
                      <p className="text-xs font-medium text-[#C4C6D0]">
                        No open drop-in sessions currently posted (sold out or league-only).
                      </p>
                      <a
                        href={rink.website_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 bg-[#323339] hover:bg-[#3C3E45] text-white text-xs font-bold px-4 py-2 rounded-full transition-all active:scale-[0.96]"
                      >
                        Check Rink Portal
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    </div>
                  )}

                  {visibleSessions.map((session) => {
                    const actionUrl = session.booking_url || session.source_url || rink.website_url;
                    return (
                      /* Elevated Dark Graphite Session Tile (#26272B) */
                      <div
                        key={session.id}
                        className="bg-[#26272B] hover:bg-[#2C2D32] rounded-[24px] p-4 space-y-3 transition-colors"
                      >
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span
                              className={`text-xs font-extrabold px-3.5 py-1 rounded-full ${getBadgeStyle(
                                session.session_type
                              )}`}
                            >
                              {session.session_type}
                            </span>
                            {session.title && (
                              <span className="text-xs text-white font-bold">
                                {session.title}
                              </span>
                            )}
                          </div>
                          {session.is_verified && (
                            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-300 bg-emerald-400/15 px-3 py-1 rounded-full">
                              <CheckCircle2 className="w-3 h-3" />
                              Verified
                            </span>
                          )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs text-[#E3E2E6]">
                          <div className="flex items-center gap-2">
                            <Calendar className="w-3.5 h-3.5 text-[#FF8992] shrink-0" />
                            <span className="font-semibold">{formatDateNice(session.session_date)}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Clock className="w-3.5 h-3.5 text-[#FF8992] shrink-0" />
                            <span className="font-semibold">
                              {formatTime12Hour(session.start_time)} –{' '}
                              {formatTime12Hour(session.end_time)}
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <DollarSign className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
                            <span className="text-[#C4C6D0] font-medium">
                              {session.cost_notes || (session.cost ? `$${session.cost}` : 'Free/Check')}
                            </span>
                          </div>
                        </div>

                        {/* Material 3 Action Pills */}
                        <div className="flex items-center justify-end gap-2 pt-2">
                          <a
                            href={actionUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 bg-[#4B9CD3]/20 hover:bg-[#4B9CD3]/30 text-[#96D0FA] text-xs font-bold px-4 py-2 rounded-full transition-all duration-150 active:scale-[0.96]"
                          >
                            {session.registration_required ? 'Register / Book' : 'Rink Schedule'}
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                          <button
                            onClick={() => handleShare(session)}
                            className="inline-flex items-center gap-1.5 bg-[#323339] hover:bg-[#3C3E45] text-[#E3E2E6] text-xs font-bold px-4 py-2 rounded-full transition-all duration-150 active:scale-[0.96] cursor-pointer"
                          >
                            <Share2 className="w-3.5 h-3.5 text-[#FF8992]" />
                            {copiedId === session.id ? 'Copied!' : 'Share'}
                          </button>
                        </div>
                      </div>
                    );
                  })}

                  {hiddenCount > 0 && (
                    <button
                      onClick={() => toggleRinkExpanded(rink.id)}
                      className="w-full py-3 bg-[#26272B] hover:bg-[#303136] rounded-full text-xs font-extrabold text-white flex items-center justify-center gap-1.5 transition-all duration-150 active:scale-[0.98] cursor-pointer"
                    >
                      {isExpanded ? (
                        <>
                          <ChevronUp className="w-4 h-4 text-[#FF8992]" />
                          Show fewer sessions
                        </>
                      ) : (
                        <>
                          <ChevronDown className="w-4 h-4 text-[#FF8992]" />
                          Show {hiddenCount} more session{hiddenCount === 1 ? '' : 's'}
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}