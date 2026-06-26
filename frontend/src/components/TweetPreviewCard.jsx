import { Heart, Repeat2, MessageCircle, Eye, CornerDownRight } from 'lucide-react';

function Metric({ Icon, value }) {
  if (value == null) return null;
  return (
    <span className="flex items-center gap-1 text-zinc-500 text-xs">
      <Icon size={12} />
      {value.toLocaleString()}
    </span>
  );
}

export default function TweetPreviewCard({ post, author, isReply = false }) {
  const m = post.public_metrics ?? {};
  const date = post.created_at ? new Date(post.created_at).toLocaleDateString() : null;

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 space-y-3">
      {isReply && (
        <p className="flex items-center gap-1 text-sky-400 text-xs font-medium">
          <CornerDownRight size={12} /> reply
        </p>
      )}
      <div className="flex items-center gap-3">
        {author.profile_image_url ? (
          <img
            src={author.profile_image_url}
            alt={author.name}
            className="w-10 h-10 rounded-full bg-zinc-800 shrink-0"
          />
        ) : (
          <div className="w-10 h-10 rounded-full bg-zinc-800 shrink-0" />
        )}
        <div className="min-w-0">
          <p className="text-white font-semibold text-sm truncate">{author.name || author.x_username}</p>
          {author.x_username && (
            <p className="text-zinc-500 text-xs">@{author.x_username}</p>
          )}
        </div>
        {date && <span className="ml-auto text-zinc-600 text-xs shrink-0">{date}</span>}
      </div>

      <p className="text-white text-sm leading-relaxed whitespace-pre-wrap">{post.text}</p>

      <div className="flex gap-4 pt-1">
        <Metric Icon={Heart} value={m.like_count} />
        <Metric Icon={Repeat2} value={m.retweet_count} />
        <Metric Icon={MessageCircle} value={m.reply_count} />
        <Metric Icon={Eye} value={m.impression_count} />
      </div>
    </div>
  );
}
