#!/usr/bin/env node
const Realm = require('realm');
const path = require('path');
const fs = require('fs');

// Get actual file path
function getAudioFilePath(lazerDir, hash) {
    if (!hash || hash.length < 2) {
        return null;
    }

    const firstChar = hash[0];
    const firstTwo = hash.substring(0, 2);
    
    return path.join(lazerDir, 'files', firstChar, firstTwo, hash);
}

async function extractBeatmapData(lazerDir) {
    const realmPath = path.join(lazerDir, 'client.realm');

    if (!fs.existsSync(realmPath)) {
        throw new Error(`client.realm not found at: ${realmPath}`);
    }

    try {
        console.log(`[Reading] ${realmPath}`);

        const realm = new Realm({
            path: realmPath,
            readOnly: true,
        });

        const beatmaps = realm.objects('Beatmap');
        const results = [];

        console.log(`[Found] ${beatmaps.length} beatmaps`);
        const beatmapArray = Array.from({ length: beatmaps.length }, (_, i) => beatmaps[i]);

        for (const beatmap of beatmapArray) {
            try {
                const difficultyName = beatmap.DifficultyName;
                const metadata = beatmap.Metadata;
                if (!metadata) continue;
                const title = String(metadata.Title || metadata.TitleUnicode || 'Unknown');
                const artist = String(metadata.Artist || metadata.ArtistUnicode || 'Unknown');
                const mapper = String(metadata.Author?.Username || 'Unknown');
                const audioFilename = String(metadata.AudioFile || '');
                const backgroundFilename = String(metadata.BackgroundFile || '');

                const beatmapSet = beatmap.BeatmapSet;
                if (!beatmapSet) continue;
                let audioHash = null;
                let backgroundHash = null;

                try {
                    if (beatmapSet.Files) {
                        for (let j = 0; j < beatmapSet.Files.length; j++) {
                            const f = beatmapSet.Files[j];
                            if (f.File && f.File.Hash) {
                                if (f.Filename === audioFilename) audioHash = String(f.File.Hash);
                                if (f.Filename === backgroundFilename) backgroundHash = String(f.File.Hash);
                            }
                        }
                    }
                } catch (fe) {}

                const audioPath = audioHash ? getAudioFilePath(lazerDir, audioHash) : null;
                const backgroundPath = backgroundHash ? getAudioFilePath(lazerDir, backgroundHash) : null;

                results.push({
                    title,
                    artist,
                    mapper,
                    difficulty: difficultyName,
                    audioFilename: audioFilename || 'Unknown',
                    audioHash,
                    audioPath,
                    fileExists: audioPath ? fs.existsSync(audioPath) : false,
                    backgroundFilename: backgroundFilename || null,
                    backgroundHash,
                    backgroundPath,
                    backgroundExists: backgroundPath ? fs.existsSync(backgroundPath) : false
                });

            } catch (beatmapError) {
                console.warn(`[Warning] Skipped beatmap: ${beatmapError.message}`);
                continue;
            }
        }

        realm.close();
        const detached = JSON.parse(JSON.stringify(results));
        console.log(`[Processed] ${results.length} beatmaps`);
        return detached;

    } catch (error) {
        throw new Error(`Failed to read realm: ${error.message}`);
    }
}

async function main() {
    const args = process.argv.slice(2);

    if (args.length === 0) {
        console.error('[Error] No osu!lazer directory provided');
        console.log('\nUsage: lazer-reader <osu-lazer-directory>');
        console.log('\nExample:');
        console.log('  Windows: lazer-reader "C:\\Users\\YourName\\AppData\\Roaming\\osu"');
        console.log('  macOS:   lazer-reader ~/Library/Application\\ Support/osu');
        console.log('  Linux:   lazer-reader ~/.local/share/osu');
        process.exit(1);
    }

    const lazerDir = args[0];

    if (!fs.existsSync(lazerDir)) {
        console.error(`[Error] Directory not found: ${lazerDir}`);
        process.exit(1);
    }

    try {
        const beatmaps = await extractBeatmapData(lazerDir);
        
        const outputPath = path.join(process.cwd(), 'lazer-audio-paths.json');
        fs.writeFileSync(outputPath, JSON.stringify(beatmaps, null, 2));
        
        console.log(`[Saved] ${outputPath}`);
        console.log(`[Summary] ${beatmaps.length} total. ${beatmaps.filter(b => b.fileExists).length} with audio, ${beatmaps.filter(b => b.backgroundExists).length} with background`);
        process.exit(0);

    } catch (error) {
        console.error(`[Fatal] ${error.message}`);
        process.exit(1);
    }
}

main();