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
      return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
    case 'Stick Time':
      return 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30';
    case 'Open Hockey':
      return 'bg-amber-500/20 text-amber-300 border border-amber-500/30';
    default:
      return 'bg-purple-500/20 text-purple-300 border border-purple-500/30';
  }
}

export default function Home() {
  const [sessions, setSessions] = useState<HockeySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [maxRadius, setMaxRadius] = useState<number>(100);
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [locationStatus, setLocationStatus] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSessions() {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];
      const { data, error: fetchError } = await supabase
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
        .limit(100);

      if (fetchError) {
        setError('Could not load sessions. Check your Supabase connection.');
      } else {
        setSessions((data as unknown as HockeySession[]) || []);
      }
      setLoading(false);
    }
    fetchSessions();
  }, []);

  const handleUseGPS = () => {
    if (!navigator.geolocation) {
      setLocationStatus('GPS not supported on this browser.');
      return;
    }
    setLocationStatus('Locating...');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocationStatus('Sorted by nearest rink');
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
      if (a.distance !== null && b.distance !== null) return a.distance - b.distance;
      return a.rink.name.localeCompare(b.rink.name);
    });
  }, [sessions, selectedType, searchQuery, maxRadius, userLocation]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-16">
      <header className="sticky top-0 z-20 bg-slate-900/95 backdrop-blur border-b border-slate-800 px-4 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-2xl">🏒</span>
              <h1 className="text-xl font-bold tracking-tight text-white">
                NJ Ice-Time Finder
              </h1>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Stick &amp; Puck • Stick Time • Open Hockey • Shinny
            </p>
          </div>
          <button
            onClick={handleUseGPS}
            className="flex items-center gap-1.5 bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs px-3 py-2 rounded-xl transition cursor-pointer"
          >
            <LocateFixed className="w-4 h-4" />
            {userLocation ? 'GPS Active' : 'Near Me'}
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 pt-5 space-y-5">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 space-y-3">
          <div className="flex flex-col sm:flex-row gap-2.5">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search rink, town, ZIP, or Cheap Skate..."
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>
            {userLocation && (
              <select
                value={maxRadius}
                onChange={(e) => setMaxRadius(Number(e.target.value))}
                className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value={10}>Within 10 miles</option>
                <option value={25}>Within 25 miles</option>
                <option value={50}>Within 50 miles</option>
                <option value={100}>Within 100 miles</option>
              </select>
            )}
          </div>

          {locationStatus && (
            <p className="text-xs text-sky-400 flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5" /> {locationStatus}
            </p>
          )}

          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <Filter className="w-4 h-4 text-slate-400 shrink-0" />
            {SESSION_CATEGORIES.map((type) => (
              <button
                key={type}
                onClick={() => setSelectedType(type)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition cursor-pointer ${
                  selectedType === type
                    ? 'bg-sky-500 text-slate-950 font-semibold'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div className="text-center py-12 text-slate-400 text-sm">
            Loading upcoming New Jersey ice times...
          </div>
        )}

        {error && (
          <div className="bg-red-950/50 border border-red-800 text-red-200 rounded-2xl p-4 text-sm flex items-start gap-2">
            <AlertCircle className="w-5 h-5 shrink-0 text-red-400 mt-0.5" />
            <div>{error}</div>
          </div>
        )}

        {!loading && !error && groupedRinks.length === 0 && (
          <div className="text-center py-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-6">
            <p className="text-slate-300 font-medium">No sessions match your filters.</p>
            <p className="text-xs text-slate-500 mt-1">
              Try clearing your search box or switching back to &ldquo;All&rdquo; session types.
            </p>
          </div>
        )}

        <div className="space-y-5">
          {groupedRinks.map(({ rink, distance, sessions: rinkSessions }) => {
            const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(
              `${rink.name}, ${rink.address}, ${rink.city}, NJ ${rink.zip_code}`
            )}`;

            return (
              <div
                key={rink.id}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-lg space-y-4"
              >
                {/* Rink Header */}
                <div className="flex items-start justify-between gap-2 border-b border-slate-800 pb-3">
                  <div>
                    <a
                      href={rink.website_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-lg font-bold text-white hover:text-sky-400 transition leading-snug inline-flex items-center gap-1.5"
                    >
                      {rink.name}
                      <ExternalLink className="w-4 h-4 text-slate-400" />
                    </a>
                    <p className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                      <MapPin className="w-3.5 h-3.5 shrink-0 text-slate-500" />
                      {rink.address}, {rink.city}, NJ {rink.zip_code}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {distance !== null && (
                      <span className="text-xs font-semibold text-sky-400 bg-sky-500/10 px-2.5 py-1 rounded-lg">
                        {distance} mi away
                      </span>
                    )}
                    <a
                      href={mapsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium px-2.5 py-1.5 rounded-lg transition"
                    >
                      <Navigation className="w-3.5 h-3.5 text-sky-400" />
                      Directions
                    </a>
                  </div>
                </div>

                {/* Sessions Inside Rink */}
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Upcoming Sessions ({rinkSessions.length})
                  </p>
                  {rinkSessions.map((session) => {
                    const actionUrl = session.booking_url || session.source_url || rink.website_url;
                    return (
                      <div
                        key={session.id}
                        className="bg-slate-950 border border-slate-800/80 rounded-xl p-3.5 space-y-2.5"
                      >
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-xs font-bold px-2.5 py-0.5 rounded-md ${getBadgeStyle(
                                session.session_type
                              )}`}
                            >
                              {session.session_type}
                            </span>
                            {session.title && (
                              <span className="text-xs text-slate-300 font-medium">
                                {session.title}
                              </span>
                            )}
                          </div>
                          {session.is_verified && (
                            <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                              <CheckCircle2 className="w-3.5 h-3.5 text-sky-400" />
                              Verified
                            </span>
                          )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs text-slate-300">
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                            <span>{formatDateNice(session.session_date)}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                            <span>
                              {formatTime12Hour(session.start_time)} –{' '}
                              {formatTime12Hour(session.end_time)}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <DollarSign className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                            <span>
                              {session.cost_notes || (session.cost ? `$${session.cost}` : 'Free/Check')}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-900">
                          <a
                            href={actionUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 bg-sky-500/15 hover:bg-sky-500/25 text-sky-400 border border-sky-500/30 text-xs font-semibold px-3 py-1.5 rounded-lg transition"
                          >
                            {session.registration_required ? 'Register / Book' : 'Rink Schedule'}
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                          <button
                            onClick={() => handleShare(session)}
                            className="inline-flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium px-2.5 py-1.5 rounded-lg transition cursor-pointer"
                          >
                            <Share2 className="w-3.5 h-3.5 text-emerald-400" />
                            {copiedId === session.id ? 'Copied!' : 'Share'}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}